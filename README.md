# SCOTUS IRAC Generator

A Flask-based web application that generates IRAC (Issue, Rule, Analysis, Conclusion) case briefs for US Supreme Court opinions using OpenAI's GPT-4 model.

## Features

- Upload SCOTUS opinion PDFs for analysis
- Generate detailed IRAC case briefs
- Role-based output formatting (Law Student or Paralegal)
- Rate limiting and file size restrictions
- Caching for improved performance
- Production-ready configuration

## Prerequisites

- Python 3.8+
- OpenAI API key
- pip (Python package manager)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/scotus-irac-generator.git
   cd scotus-irac-generator
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   - Copy `.env.example` to `.env`

## Deploying to Render.com

1. **Create a free Render.com account** at [https://render.com](https://render.com)
2. **Create a new Web Service**
   - Choose "Python" as the environment
   - Connect your GitHub repository or upload your project as a ZIP
3. **Set the build and start commands:**
   - **Build Command:** (leave blank or use `pip install -r requirements.txt`)
   - **Start Command:** `gunicorn wsgi:app`
4. **Add environment variables**
   - Add your `OPENAI_API_KEY` (from your OpenAI account)
   - (Optional) Add any other variables from `.env.example`
5. **Deploy!**
   - Click "Create Web Service" and wait for deployment to finish
   - Your app will be live at the provided Render.com URL

**Note:** For low-traffic, the free tier is usually enough. If you need more, Render.com can scale up easily.

## Configuration

Edit the `.env` file with your configuration:

```env
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Optional
FLASK_SECRET_KEY=your_secret_key_here
FLASK_DEBUG=false
ALLOWED_ORIGINS=*
PORT=5002
```

## Running the Application

### Development Mode

```bash
flask --app app_new.py run --port 5002
```

### Production Mode

Using Gunicorn:

```bash
gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT app_new:app
```

The application will be available at `http://localhost:5002`

## API Endpoints

- `GET /` - Serves the web interface
- `GET /api/health` - Health check endpoint
- `POST /api/generate_irac` - Generate IRAC analysis from PDF
  - Required form data: `file` (PDF), `role` (law_student|paralegal), `case_name`

## Deployment

### Railway

1. Create a new Railway project
2. Connect your GitHub repository
3. Add environment variables from your `.env` file
4. Deploy!

## Rate Limiting

The API is rate limited to:
- 100 requests per day
- 30 requests per hour

## File Uploads

- Maximum file size: 16MB
- Allowed file type: PDF only
- Uploads are stored in the `uploads/` directory (not persisted in production on Railway)

## Security

- Input sanitization to prevent injection attacks
- CORS configured to restrict origins
- API key stored in environment variables
- Rate limiting to prevent abuse
- File type and size restrictions

## Troubleshooting

- **API Key Issues**: Ensure `OPENAI_API_KEY` is set in your environment variables
- **File Uploads**: Check file size and type restrictions
- **Rate Limiting**: Check response headers for rate limit information
- **Logs**: Check application logs for detailed error messages

## License

MIT License - see the LICENSE file for details.
