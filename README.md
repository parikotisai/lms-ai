# AI Learning Quest Backend

A comprehensive Flask-based backend service for AI-powered programming education, supporting multiple programming languages with interactive code execution and AI tutoring capabilities.

## 🚀 Features

### Core Functionality
- **Multi-Language Support**: Python, JavaScript, Java, C#, and Selenium WebDriver
- **AI-Powered Learning**: Syllabus generation, lesson creation, code explanation, and AI chat tutoring
- **Interactive Code Execution**: Safe execution environment for multiple programming languages
- **User Authentication**: Registration and login system with secure password hashing
- **Database Integration**: SQLite database with SQLAlchemy ORM

### Language-Specific Features

#### JavaScript
- **Browser Environment Simulation**: DOM API simulation for client-side code
- **HTML Support**: Execute JavaScript with HTML context
- **Environment Detection**: Automatic detection of browser vs Node.js code
- **Enhanced Execution**: Support for modern JavaScript features

#### Python
- **Framework Support**: pytest, unittest frameworks
- **Safe Execution**: Isolated execution environment
- **Error Analysis**: AI-powered error explanation and debugging

#### Java
- **Framework Support**: JUnit, TestNG, Cucumber (BDD)
- **Compilation & Execution**: Full Java development workflow
- **BDD Testing**: Cucumber with Gherkin syntax support

#### C#
- **Framework Support**: NUnit, MSTest frameworks
- **.NET Integration**: Full .NET SDK support
- **Project Management**: Automatic project structure creation

#### Selenium WebDriver
- **Multi-Language Support**: Python, Java, JavaScript, C# bindings
- **Framework Integration**: pytest, TestNG, JUnit, NUnit, Mocha, Jest
- **Cross-Browser Testing**: WebDriver automation capabilities

## 🛠️ Technology Stack

- **Backend**: Flask (Python web framework)
- **Database**: SQLite with SQLAlchemy ORM
- **AI Integration**: Groq API (Llama-3.3-70b-versatile) & Google Gemini
- **Authentication**: Werkzeug security (password hashing)
- **CORS Support**: Flask-CORS for cross-origin requests
- **Code Execution**: Subprocess-based execution with safety timeouts
- **Environment**: Python virtual environment

## 📋 Prerequisites

- **Python 3.8+**
- **Node.js** (for JavaScript execution)
- **Java JDK** (for Java execution)
- **.NET SDK** (for C# execution)
- **Git** (for version control)

## 🚀 Installation & Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd ai-learning-quest-backend
```

### 2. Create Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install flask flask-cors flask-sqlalchemy python-dotenv groq google-generativeai werkzeug
```

### 4. Environment Configuration
Create a `.env` file in the root directory:
```env
GOOGLE_API_KEY=your_google_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### 5. Run the Application
```bash
python app.py
```

The server will start on `http://127.0.0.1:5002`

## 📚 API Endpoints

### Authentication
- `POST /register` - User registration
- `POST /login` - User login

### AI Learning Features
- `POST /generate-syllabus` - Generate programming syllabus
- `POST /generate-lesson` - Generate interactive lessons
- `POST /explain-code` - Explain code with AI assistance
- `POST /chat-with-ai` - Chat with AI programming tutor

### Code Execution
- `POST /run-code` - Execute code in multiple languages

### System
- `GET /` - Home page
- `GET /health` - Health check with system status

## 🔧 API Usage Examples

### Generate Syllabus
```bash
curl -X POST http://localhost:5002/generate-syllabus \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "domain": "web-development",
    "difficulty": "Medium",
    "skillLevel": "Intermediate"
  }'
```

### Execute Code
```bash
curl -X POST http://localhost:5002/run-code \
  -H "Content-Type: application/json" \
  -d '{
    "code": "print(\"Hello, World!\")",
    "language": "python"
  }'
```

### Chat with AI
```bash
curl -X POST http://localhost:5002/chat-with-ai \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I create a function in Python?",
    "language": "python"
  }'
```

## 🏗️ Architecture

### Code Execution Security
- **Isolated Execution**: Each code execution runs in separate processes
- **Resource Limits**: CPU and memory limits to prevent abuse
- **Timeout Protection**: 10-second execution timeout
- **File System Isolation**: Temporary directories for code execution

### AI Integration
- **Dual Provider Support**: Groq (primary) and Google Gemini (fallback)
- **Structured Output**: JSON-formatted responses for consistent parsing
- **Error Handling**: Graceful degradation when AI services are unavailable

### Database Schema
```sql
-- Users table
CREATE TABLE user (
    id INTEGER PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL
);
```

## 🔒 Security Considerations

### For Development/Testing
- **Debug Mode**: Enabled for development (disable in production)
- **CORS**: Configured for cross-origin requests
- **Environment Variables**: Sensitive keys stored securely

### Production Deployment
⚠️ **WARNING**: This application contains code execution capabilities that can be dangerous in production environments.

**Recommended Security Measures:**
- Deploy in isolated containers (Docker)
- Use reverse proxy (Nginx) with proper security headers
- Implement rate limiting and request validation
- Disable debug mode
- Use production WSGI server (Gunicorn)
- Regular security audits and dependency updates

## 🧪 Testing

### Manual Testing
1. **Health Check**: `GET /health`
2. **User Registration**: Test signup/login flow
3. **Code Execution**: Test each supported language
4. **AI Features**: Test syllabus generation and chat functionality

### Language-Specific Testing
- **Python**: Basic syntax, functions, classes
- **JavaScript**: Browser APIs, Node.js modules
- **Java**: Compilation, execution, frameworks
- **C#**: .NET features, frameworks
- **Selenium**: WebDriver automation

## 📊 Supported Frameworks

| Language | Frameworks | Testing Frameworks |
|----------|------------|-------------------|
| Python | Flask, Django | pytest, unittest |
| JavaScript | React, Node.js | Mocha, Jest |
| Java | Spring, Hibernate | JUnit, TestNG, Cucumber |
| C# | ASP.NET, Entity Framework | NUnit, MSTest |
| Selenium | WebDriver | All language-specific frameworks |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new features
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Troubleshooting

### Common Issues

**"Command not found" errors:**
- Ensure all required runtimes are installed (Node.js, Java, .NET)
- Check PATH environment variables

**AI API errors:**
- Verify API keys in `.env` file
- Check API rate limits and quotas
- Ensure internet connectivity

**Database errors:**
- Check file permissions for SQLite database
- Ensure database migrations are run

**Code execution timeouts:**
- Complex code may exceed 10-second limit
- Optimize code or increase timeout (not recommended for production)

## 📞 Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review API documentation

## 🔄 Version History

- **v1.0.0**: Initial release with multi-language support
- **v1.1.0**: Enhanced JavaScript execution with browser simulation
- **v1.2.0**: Added Selenium WebDriver support
- **v1.3.0**: Improved AI integration and error handling

---

**Built with ❤️ for programming education and interactive learning**