import os
import logging
import time
import re
import json
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

# Configuration for file uploads
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_EXTENSIONS'] = ['.pdf']
app.config['UPLOAD_PATH'] = 'uploads'  # Create this directory if it doesn't exist

# Get OpenAI API key from environment variable
openai_api_key = os.environ.get('OPENAI_API_KEY')
if not openai_api_key:
    raise ValueError("No OPENAI_API_KEY environment variable set. Please set it in your Render environment variables.")

# Initialize OpenAI client
openai.api_key = openai_api_key

def extract_text_from_pdf(pdf_file):
    """Extract text from a PDF file."""
    try:
        reader = PdfReader(pdf_file)
        return ' '.join([page.extract_text() or '' for page in reader.pages])
    except Exception as e:
        print(f"PDF Error: {str(e)}")
        return ""

@app.route('/api/generate_irac', methods=['POST'])
def generate_irac():
    try:
        # Get PDF file
        if 'pdf' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
            
        pdf = request.files['pdf']
        if not pdf.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'File must be a PDF'}), 400
        
        # Extract text
        case_text = extract_text_from_pdf(pdf)
        if not case_text.strip():
            return jsonify({'error': 'Could not read PDF content'}), 400
        
        # Get form data with defaults
        role = request.form.get('role', 'student')
        case_name = request.form.get('caseName', 'Case')
        docket_number = request.form.get('docketNumber', '')
        
        # Simple prompt
        prompt = f"""Create an IRAC (Issue, Rule, Analysis, Conclusion) summary for this legal case.
        Case: {case_name}
        Role: {role}
        
        {case_text[:3000]}
        
        Provide a clear IRAC analysis in plain text.
        """
        
        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3
        )
        
        return jsonify({'summary': response.choices[0].message.content.strip()})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Failed to process request'}), 500
    
    # Add docket number to the case name if provided
    if docket_number:
        case_name = f"{case_name} (Docket No. {docket_number})" if case_name else f"Docket No. {docket_number}"

    if role == 'student':
        prompt = f"""You are a law professor creating study materials for your students. Read the following Supreme Court case and generate a comprehensive IRAC (Issue, Rule, Application, Conclusion) analysis with these sections:
            prompt = f"""You are a law professor creating study materials for your students. Read the following Supreme Court case and generate a comprehensive IRAC (Issue, Rule, Application, Conclusion) analysis with these sections:

### CASE CITATION
- Full case name and citation
- Court term and decision date

### VOTING ALIGNMENT
- Vote: [e.g., 6-3, 9-0, 5-4] - Must include the actual vote count
- Majority by: [Justice Name] - Specify the justice who wrote the majority opinion
- Joined by: [List all Justices in the majority] - Include all justices who joined
- Dissenting: [List all dissenting Justices] - Include 'None' if unanimous
- Concurring: [List any concurring Justices with their reasoning] - Include 'None' if none

### KEY FACTS
- 3-5 most important facts that influenced the Court's decision
- Focus on legally significant facts

### PROCEDURAL HISTORY
- Lower court decisions
- How the case reached this court

### ISSUE
- The precise legal question before the Court
- Frame it as a yes/no or either/or question

### RULE
- The legal principle(s) the Court applies
- Relevant precedent and its evolution
- Any competing legal standards

### ANALYSIS/APPLICATION
- Court's reasoning and legal analysis
- Application of law to facts
- Key policy considerations
- Competing views (concurrences/dissents if present)

### HOLDING
- The Court's specific decision
- Vote count and author of the opinion
- Any notable concurrences or dissents

### SIGNIFICANCE
• **Broader legal doctrine**: How this case fits into the larger legal framework
• **Future impact**: Potential implications for future cases and legal arguments
• **Educational value**: Why this case is significant in legal education
• **Policy considerations**: Any policy implications of the Court's decision

### PRECEDENTIAL VALUE
• **Controls current case?**: [Yes/No - Explain why this is or isn't the controlling precedent for the legal issue]
• **Distinguishable because:** [Explain specific factual or legal differences that would make this case inapplicable to other situations, or state 'Not applicable' if broadly applicable]
• **Potentially overruled by:** [List any subsequent cases that have directly criticized, limited, or overruled this decision, or 'None' if still good law]
• **Key case for:** [List 2-3 specific legal principles or doctrines this case is most frequently cited for, with brief explanations]
• **Jurisdictional reach:** [Specify if this is binding only in certain circuits or has nationwide application]

Case Text:
{case_text[:4000]}

Format the response in clear, well-structured markdown with bold section headers. Use headings, subheadings, and bullet points for readability. Include relevant case law citations where appropriate."""
        else:  # paralegal
            prompt = f"""You are a senior paralegal preparing a case brief for an attorney. For the case Trump v. United States (2024), ensure you provide complete and accurate information in all sections. If information is not available in the provided text, indicate 'Not specified in provided text'. Create a concise, practical IRAC summary with these sections:

### CASE CITATION
- Case name and citation
- Court and decision date

### VOTING ALIGNMENT
- Vote: [e.g., 6-3, 9-0, 5-4] - Must include the actual vote count
- Majority by: [Justice Name] - Specify the justice who wrote the majority opinion
- Joined by: [List all Justices in the majority] - Include all justices who joined
- Dissenting: [List all dissenting Justices] - Include 'None' if unanimous
- Concurring: [List any concurring Justices with their reasoning] - Include 'None' if none

### CASE STATUS
- [ ] Binding precedent (check if applicable)
- [ ] Persuasive authority (check if applicable)
- [ ] Overruled/Narrowed by: [List any cases that have overruled or narrowed this decision, or 'None' if still good law]
- [ ] Impact on existing precedent: [Describe how this affects previous rulings]

### KEY HOLDING
- The Court's main decision in 1-2 sentences
- The specific legal rule established

### PRECEDENTIAL VALUE
• **Controls current case?**: [Yes/No - Explain why this is or isn't the controlling precedent for the legal issue]
• **Distinguishable because:** [Explain specific factual or legal differences that would make this case inapplicable to other situations, or state 'Not applicable' if broadly applicable]
• **Potentially overruled by:** [List any subsequent cases that have directly criticized, limited, or overruled this decision, or 'None' if still good law]
• **Key case for:** [List 2-3 specific legal principles or doctrines this case is most frequently cited for, with brief explanations]
• **Jurisdictional reach:** [Specify if this is binding only in certain circuits or has nationwide application]

### PRACTICAL APPLICATION
• How to use this case in arguments
• When to cite it
• How it affects current law

### RELATED AUTHORITY
• **Key statutes:** [List relevant statutes and code sections]
• **Supporting cases:** [List and briefly describe cases that support this decision]
• **Contrary cases:** [List and briefly describe cases that might conflict with this decision]
• **Secondary sources:** [List relevant law review articles, treatises, or other commentary]

### PRACTICE TIPS
• **Best uses in litigation:** [Describe the most effective ways to use this case in legal arguments]
• **Potential weaknesses:** [Note any limitations or weaknesses in the Court's reasoning]
• **Distinguishing factors:** [Explain how to distinguish this case from unfavorable precedent]
• **Drafting guidance:** [Tips for citing this case in briefs and motions]

Case Text:
{case_text[:4000]}

Keep it under 500 words. Use bullet points and clear headers. Focus on practical implications and how to use this case in practice. Include checkboxes for quick reference. Highlight any language that would be persuasive in a brief or motion."""

        try:
            logger.info("Prompt built successfully")
            
            # Log the first 500 chars of the prompt for debugging
            logger.debug(f"Prompt preview: {prompt[:500]}...")
            
            # Check if OpenAI API key is set
            if not openai.api_key:
                error_msg = "OpenAI API key is not configured"
                logger.error(error_msg)
                return jsonify({'error': error_msg}), 500
                
            # Generate IRAC summary using OpenAI
            logger.info("Sending request to OpenAI...")
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=700,
                temperature=0.3
            )
            
            if not response.choices or not response.choices[0].message.content:
                error_msg = "Received empty response from OpenAI"
                logger.error(error_msg)
                return jsonify({'error': error_msg}), 500
                
            irac_summary = response.choices[0].message.content.strip()
            logger.info("Successfully received response from OpenAI")
            return jsonify({'summary': irac_summary})
            
        except openai.AuthenticationError as e:
            error_msg = "Authentication failed with OpenAI. Please check your API key."
            logger.error(f"{error_msg} Error: {str(e)}")
            return jsonify({'error': error_msg}), 401
            
        except openai.RateLimitError as e:
            error_msg = "Rate limit exceeded. Please try again later."
            logger.error(f"{error_msg} Error: {str(e)}")
            return jsonify({'error': error_msg}), 429
            
        except openai.APIError as e:
            error_msg = f"OpenAI API error: {str(e)}"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 500
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Error in generate_irac: {error_msg}", exc_info=True)
            return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500
            
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({'error': f'Error processing request: {str(e)}'}), 500

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(path):
        return send_from_directory('.', path)
    return 'Not Found', 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5010))
    app.run(host='0.0.0.0', port=port)
