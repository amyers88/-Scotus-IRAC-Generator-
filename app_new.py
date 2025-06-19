import os
import logging
import time
import re
import json
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import openai
import PyPDF2
from cachetools import TTLCache
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Constants
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'pdf'}
RATE_LIMIT = "100 per day; 30 per hour"
OPENAI_TIMEOUT = 30  # seconds

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, static_folder='.', static_url_path='')

# App configuration
app.config.update(
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    UPLOAD_FOLDER=os.path.join(os.getcwd(), 'uploads'),
    ALLOWED_EXTENSIONS=ALLOWED_EXTENSIONS,
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())
)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT],
    storage_uri="memory://"
)

# Configure CORS
CORS(app, resources={
    r"/*": {
        "origins": os.getenv('ALLOWED_ORIGINS', '*').split(','),
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Initialize OpenAI client
openai.api_key = os.getenv('OPENAI_API_KEY')
if not openai.api_key:
    logger.error("OPENAI_API_KEY not found in environment variables")
    raise ValueError("OPENAI_API_KEY environment variable is required")

# Response cache (5 min TTL)
response_cache = TTLCache(maxsize=100, ttl=300)

# Helper functions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def sanitize_input(text):
    """Basic input sanitization"""
    if not text:
        return ""
    # Remove any non-printable characters except newlines
    return re.sub(r'[^\x20-\x7E\n]', '', str(text))

def generate_cache_key(*args):
    """Generate a cache key from function arguments"""
    return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()

def extract_text_from_pdf(pdf_file):
    """Extract text from a PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        raise ValueError("Failed to extract text from PDF")

# Error handlers
@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error)}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found", "message": "The requested resource was not found"}), 404

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File too large", "message": f"File size exceeds {MAX_CONTENT_LENGTH//1024//1024}MB limit"}), 413

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Rate limit exceeded", "message": str(e.description)}), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error", "message": "An unexpected error occurred"}), 500

# Routes
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.route('/api/generate_irac', methods=['POST'])
@limiter.limit(RATE_LIMIT)
def generate_irac():
    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        
        # Check if file is selected
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
            
        # Validate file type and size
        if not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type. Only PDF files are allowed."}), 400
            
        # Get role and case name
        role = request.form.get('role', 'law_student')
        case_name = sanitize_input(request.form.get('case_name', 'Unnamed Case'))
        
        # Generate cache key
        cache_key = generate_cache_key(file.filename, role, case_name)
        
        # Check cache
        if cache_key in response_cache:
            logger.info("Cache hit")
            return jsonify(response_cache[cache_key])
            
        # Extract text from PDF
        try:
            text = extract_text_from_pdf(file)
            if not text.strip():
                return jsonify({"error": "The uploaded PDF appears to be empty or could not be read"}), 400
        except Exception as e:
            logger.error(f"PDF processing error: {str(e)}")
            return jsonify({"error": "Error processing PDF file"}), 400
        
        # Build prompt based on role
        if role == 'law_student':
            prompt = f"""Generate a detailed IRAC analysis for the following case: {case_name}
            
            {text}
            
            Please structure your response with these sections:
            1. Case Citation
            2. Procedural History
            3. Issues
            4. Rules
            5. Analysis
            6. Conclusion
            7. Significance
            8. Related Cases
            
            Include proper legal citations and analysis."""
        else:  # paralegal
            prompt = f"""Create a concise case summary for {case_name} with these sections:
            
            {text}
            
            1. Case Citation
            2. Key Facts
            3. Holding
            4. Rule of Law
            5. Practical Implications
            6. Checklist for Use
            
            Focus on practical applications and use bullet points for readability."""
        
        # Call OpenAI API
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a legal expert providing case analysis."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3
            )
            
            result = {
                "analysis": response.choices[0].message['content'],
                "model": response.model,
                "usage": dict(response.usage),
                "cached": False
            }
            
            # Cache the result
            response_cache[cache_key] = result
            result["cached"] = False
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            return jsonify({"error": "Error generating analysis. Please try again later."}), 500
            
    except RequestEntityTooLarge:
        return jsonify({"error": "File too large"}), 413
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
