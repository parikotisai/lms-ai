import os
import io
import contextlib
import subprocess
import tempfile
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import re
import json
import logging

from werkzeug.security import generate_password_hash, check_password_hash

# --- Import BOTH clients ---
from groq import Groq
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold # For Gemini safety settings
from flask_sqlalchemy import SQLAlchemy

# --- Configuration & Setup ---

load_dotenv() # Load environment variables from .env file

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Get BOTH API Keys ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GOOGLE_API_KEY:
    print("Warning: GOOGLE_API_KEY not found in .env. Gemini functionality may be limited.")
if not GROQ_API_KEY:
    print("Warning: GROQ_API_KEY not found in .env. Groq functionality may be limited.")

# --- Initialize BOTH clients ---
gemini_model = None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash') # Gemini model for text generation

groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
    GROQ_MODEL_NAME = "llama-3.3-70b-versatile" # Placeholder: Replace with the exact Groq model name you want to use


# --- CHOOSE YOUR DEFAULT LLM PROVIDER HERE ---
DEFAULT_LLM_PROVIDER = 'GROQ' # <--- Set your preferred default here

app = Flask(__name__)
CORS(app)

# --- NEW: Database Configuration ---
# Use SQLite for development. The database file will be named 'site.db' in the project folder.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable signal tracking as it's not needed

db = SQLAlchemy(app) # Initialize SQLAlchemy with your Flask app

# --- NEW: Define Database Models (Tables) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False) # Store hashed passwords, not raw
    # You can add more fields here later, like:
    # xp = db.Column(db.Integer, default=0)
    # last_lesson_completed = db.Column(db.String(100))

    def __repr__(self):
        return f'<User {self.username}>'


# --- Language Configuration ---
SUPPORTED_LANGUAGES = {
    'python': {
        'extension': '.py',
        'command': 'python3',
        'frameworks': ['pytest', 'unittest'],
        'domains': ['web-development', 'data-science', 'automation-testing', 'game-development', 'mobile-development']
    },
    'javascript': {
        'extension': '.js',
        'command': 'node',
        'frameworks': ['mocha', 'jest'],
        'domains': ['web-development', 'game-development', 'mobile-development', 'automation-testing']
    },
    'java': {
        'extension': '.java',
        'command': 'java',
        'compile_command': 'javac',
        'frameworks': ['junit', 'testng', 'cucumber'],
        'domains': ['web-development', 'mobile-development', 'game-development', 'automation-testing']
    },
    'csharp': {
        'extension': '.cs',
        'command': 'dotnet run',
        'frameworks': ['nunit', 'xunit'],
        'domains': ['web-development', 'game-development', 'mobile-development', 'automation-testing']
    },
    'selenium': {
        'sub_languages': {
            'python': {'framework': 'pytest', 'imports': 'from selenium import webdriver'},
            'java': {'framework': 'TestNG', 'imports': 'import org.openqa.selenium.WebDriver;'},
            'javascript': {'framework': 'Mocha', 'imports': 'const {Builder} = require("selenium-webdriver");'},
            'csharp': {'framework': 'NUnit', 'imports': 'using OpenQA.Selenium;'}
        },
        'domain': 'automation-testing'
    }
}

# --- Enhanced JavaScript Functions ---
def detect_javascript_type(code):
    """
    Detect the type of JavaScript code to determine execution environment
    Returns: 'browser_js', 'node_js', or 'vanilla_js'
    """
    
    # Browser/DOM-specific patterns
    browser_patterns = [
        r'\bdocument\.',
        r'\bwindow\.',
        r'\balert\s*\(',
        r'\bprompt\s*\(',
        r'\bconfirm\s*\(',
        r'\bconsole\.log\s*\(',
        r'\blocalStorage\.',
        r'\bsessionStorage\.',
        r'\.getElementById\s*\(',
        r'\.querySelector\s*\(',
        r'\.addEventListener\s*\(',
        r'\bfetch\s*\(',
        r'<\s*html|<\s*body|<\s*div|<\s*script',  # HTML tags
    ]
    
    # Node.js-specific patterns
    node_patterns = [
        r'\brequire\s*\(',
        r'\bmodule\.exports',
        r'\bexports\.',
        r'\bprocess\.',
        r'\b__dirname\b',
        r'\b__filename\b',
        r'\bfs\.',
        r'\bpath\.',
    ]
    
    # Check for browser patterns
    for pattern in browser_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            logger.debug(f"Detected browser pattern: {pattern}")
            return 'browser_js'
    
    # Check for Node.js patterns
    for pattern in node_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            logger.debug(f"Detected Node.js pattern: {pattern}")
            return 'node_js'
    
    # Default to vanilla JavaScript
    return 'vanilla_js'

def simulate_browser_environment(code):
    """
    Add browser API simulations to JavaScript code
    """
    browser_simulation = '''
// Browser API Simulations
const document = {
    getElementById: (id) => ({ 
        innerHTML: '', 
        textContent: '', 
        value: '',
        style: {},
        addEventListener: () => {},
        id: id 
    }),
    querySelector: (selector) => ({ 
        innerHTML: '', 
        textContent: '', 
        value: '',
        style: {},
        addEventListener: () => {},
        className: '' 
    }),
    createElement: (tag) => ({ 
        innerHTML: '', 
        textContent: '', 
        value: '',
        style: {},
        appendChild: () => {},
        addEventListener: () => {},
        tagName: tag.toUpperCase()
    }),
    body: { 
        appendChild: () => {},
        style: {} 
    }
};

const window = {
    alert: (msg) => console.log('ALERT:', msg),
    prompt: (msg, defaultValue = '') => {
        console.log('PROMPT:', msg);
        return defaultValue || 'Hello, JavaScript User!';
    },
    confirm: (msg) => {
        console.log('CONFIRM:', msg);
        return true;
    },
    localStorage: {
        getItem: (key) => null,
        setItem: (key, value) => console.log(`LocalStorage SET: ${key} = ${value}`),
        removeItem: (key) => console.log(`LocalStorage REMOVE: ${key}`)
    },
    location: { href: 'http://localhost:3000' }
};

const alert = window.alert;
const prompt = window.prompt;
const confirm = window.confirm;
const localStorage = window.localStorage;

'''
    return browser_simulation + '\n' + code

# --- Helper function to make API calls to chosen provider ---
def call_llm(messages_list, provider, response_format_type=None, temperature=0.7, max_tokens=1024):
    if provider == 'GEMINI':
        if not gemini_model:
            raise ValueError("Gemini model not initialized. Check GOOGLE_API_KEY.")
        
        # Gemini's generate_content 'contents' parameter expects a list of parts.
        gemini_contents = []
        for msg in messages_list:
            if msg['role'] == 'system':
                if gemini_contents and gemini_contents[0]['role'] == 'user':
                    gemini_contents[0]['parts'][0] = msg['content'] + "\n\n" + gemini_contents[0]['parts'][0]
                else:
                    gemini_contents.append({"role": "user", "parts": [msg['content']]})
            elif msg['role'] == 'user':
                gemini_contents.append({"role": "user", "parts": [msg['content']]})
            elif msg['role'] == 'assistant':
                gemini_contents.append({"role": "model", "parts": [msg['content']]})

        generation_config = None
        if response_format_type == "json_object":
            generation_config = {"response_mime_type": "application/json"}

        response = gemini_model.generate_content(
            contents=gemini_contents,
            generation_config=generation_config,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        if not response._result.candidates:
            raise Exception("AI response was blocked by Gemini's safety settings.")
        return response.text

    elif provider == 'GROQ':
        if not groq_client:
            raise ValueError("Groq client not initialized. Check GROQ_API_KEY.")
        
        groq_response_format = {"type": response_format_type} if response_format_type else None

        chat_completion = groq_client.chat.completions.create(
            messages=messages_list,
            model=GROQ_MODEL_NAME,
            response_format=groq_response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return chat_completion.choices[0].message.content
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


# --- Code Execution Functions ---

def execute_python_code(code_to_run):
    """Execute Python code safely"""
    old_stdout = io.StringIO()
    redirect_stdout = contextlib.redirect_stdout(old_stdout)

    raw_error_output = ""
    captured_output = ""
    ai_feedback = ""

    try:
        with redirect_stdout:
            exec(code_to_run, {}, {})
        captured_output = old_stdout.getvalue()
    except Exception as e:
        raw_error_output = str(e)
        captured_output = ""

        feedback_prompt_messages = [
            {
                "role": "system",
                "content": """You are an expert, patient, and friendly Python programming tutor.
                Please explain this error in simple terms that a complete beginner can understand.
                Then, provide a clear, concise suggestion on how to fix this error.
                Do NOT provide the corrected code directly unless absolutely necessary for clarity,
                focus on explaining the concept and the fix.

                Format your response as a JSON object with two keys:
                "explanation": "A beginner-friendly explanation of the error.",
                "suggestion": "A clear suggestion on how to fix it."
                """
            },
            {"role": "user", "content": f"My code is:\n```python\n{code_to_run}\n```\nThe raw Python error message is: \"{raw_error_output}\""}
        ]
        try:
            ai_feedback = call_llm(feedback_prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", temperature=0.5, max_tokens=1024)
        except Exception as ai_e:
            print(f"Error generating AI feedback from {DEFAULT_LLM_PROVIDER}: {ai_e}")
            ai_feedback = json.dumps({"explanation": "Could not generate AI feedback due to an internal error.", "suggestion": "Please check your code carefully."})

    return jsonify({
        "output": captured_output,
        "raw_error": raw_error_output,
        "ai_feedback": ai_feedback
    }), 200


def execute_javascript_code(code_to_run):
    """Enhanced JavaScript execution with environment detection and HTML support"""
    try:
        logger.debug(f"Executing JavaScript code: {code_to_run[:100]}...")
        
        # Detect JavaScript type
        js_type = detect_javascript_type(code_to_run)
        logger.debug(f"Detected JavaScript type: {js_type}")
        
        # Prepare code based on type
        if js_type == 'browser_js':
            # Add browser environment simulation
            enhanced_code = simulate_browser_environment(code_to_run)
        else:
            # For vanilla_js and node_js, use code as-is
            enhanced_code = code_to_run
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as temp_file:
            temp_file.write(enhanced_code)
            temp_file_path = temp_file.name
        
        try:
            # Execute with Node.js
            result = subprocess.run(
                ['node', temp_file_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                return jsonify({
                    "output": output if output else 'Code executed successfully (no output)',
                    "raw_error": "",
                    "ai_feedback": "",
                    "environment": js_type
                }), 200
            else:
                return generate_error_feedback(code_to_run, result.stderr, 'JavaScript', js_type)
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except subprocess.TimeoutExpired:
        return jsonify({
            "output": "",
            "raw_error": "Code execution timed out",
            "ai_feedback": json.dumps({
                "explanation": "Your JavaScript code took too long to execute (over 10 seconds).",
                "suggestion": "Check for infinite loops or optimize your code."
            }),
            "environment": js_type if 'js_type' in locals() else 'unknown'
        }), 200
    except FileNotFoundError:
        return jsonify({
            "output": "",
            "raw_error": "Node.js not found",
            "ai_feedback": json.dumps({
                "explanation": "Node.js is not installed or not found in PATH.",
                "suggestion": "Install Node.js to run JavaScript code."
            }),
            "environment": js_type if 'js_type' in locals() else 'unknown'
        }), 200
    except Exception as e:
        logger.error(f"JavaScript execution error: {str(e)}")
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "An unexpected error occurred during JavaScript execution.",
                "suggestion": "Please check your code syntax and try again."
            }),
            "environment": js_type if 'js_type' in locals() else 'unknown'
        }), 200


def execute_java_code(code_to_run):
    """Execute Java code (basic implementation)"""
    try:
        # Extract class name from code
        class_match = re.search(r'public\s+class\s+(\w+)', code_to_run)
        if not class_match:
            return jsonify({
                "output": "",
                "raw_error": "No public class found",
                "ai_feedback": json.dumps({
                    "explanation": "Java code must have a public class with a main method.",
                    "suggestion": "Make sure your code has 'public class ClassName' and 'public static void main(String[] args)'."
                })
            }), 200
        
        class_name = class_match.group(1)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            java_file = os.path.join(temp_dir, f"{class_name}.java")
            with open(java_file, 'w') as f:
                f.write(code_to_run)
            
            # Compile
            compile_result = subprocess.run(
                ['javac', java_file],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if compile_result.returncode != 0:
                return generate_error_feedback(code_to_run, compile_result.stderr, 'Java')
            
            # Run
            run_result = subprocess.run(
                ['java', '-cp', temp_dir, class_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if run_result.returncode == 0:
                return jsonify({
                    "output": run_result.stdout,
                    "raw_error": "",
                    "ai_feedback": ""
                }), 200
            else:
                return generate_error_feedback(code_to_run, run_result.stderr, 'Java')
                
    except subprocess.TimeoutExpired:
        return jsonify({
            "output": "",
            "raw_error": "Code execution timed out",
            "ai_feedback": json.dumps({
                "explanation": "Your Java code took too long to compile or execute.",
                "suggestion": "Check for infinite loops or optimize your code."
            })
        }), 200
    except FileNotFoundError:
        return jsonify({
            "output": "",
            "raw_error": "Java not found",
            "ai_feedback": json.dumps({
                "explanation": "Java compiler (javac) or runtime (java) not found.",
                "suggestion": "Install Java JDK to compile and run Java code."
            })
        }), 200
    except Exception as e:
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "An unexpected error occurred during Java execution.",
                "suggestion": "Please check your code syntax and try again."
            })
        }), 200


def execute_csharp_code(code_to_run):
    """Execute C# code using dotnet"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a simple console project
            project_result = subprocess.run(
                ['dotnet', 'new', 'console', '--force'],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if project_result.returncode != 0:
                return jsonify({
                    "output": "",
                    "raw_error": "Failed to create C# project",
                    "ai_feedback": json.dumps({
                        "explanation": "Could not create a C# console project.",
                        "suggestion": "Make sure .NET SDK is properly installed."
                    })
                }), 200
            
            # Write the code
            program_file = os.path.join(temp_dir, "Program.cs")
            with open(program_file, 'w') as f:
                f.write(code_to_run)
            
            # Run the code
            run_result = subprocess.run(
                ['dotnet', 'run'],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if run_result.returncode == 0:
                return jsonify({
                    "output": run_result.stdout,
                    "raw_error": "",
                    "ai_feedback": ""
                }), 200
            else:
                return generate_error_feedback(code_to_run, run_result.stderr, 'C#')
                
    except subprocess.TimeoutExpired:
        return jsonify({
            "output": "",
            "raw_error": "Code execution timed out",
            "ai_feedback": json.dumps({
                "explanation": "Your C# code took too long to compile or execute.",
                "suggestion": "Check for infinite loops or optimize your code."
            })
        }), 200
    except FileNotFoundError:
        return jsonify({
            "output": "",
            "raw_error": ".NET not found",
            "ai_feedback": json.dumps({
                "explanation": ".NET SDK is not installed or not found in PATH.",
                "suggestion": "Install .NET SDK to compile and run C# code."
            })
        }), 200
    except Exception as e:
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "An unexpected error occurred during C# execution.",
                "suggestion": "Please check your code syntax and try again."
            })
        }), 200


def generate_error_feedback(code, error_message, language, js_environment=None):
    """Generate AI feedback for code errors"""
    env_info = f" (detected as {js_environment})" if js_environment else ""
    
    feedback_prompt_messages = [
        {
            "role": "system",
            "content": f"""You are an expert, patient, and friendly {language} programming tutor.
            Please explain this error in simple terms that a complete beginner can understand.
            Then, provide a clear, concise suggestion on how to fix this error.
            Do NOT provide the corrected code directly unless absolutely necessary for clarity,
            focus on explaining the concept and the fix.

            Format your response as a JSON object with two keys:
            "explanation": "A beginner-friendly explanation of the error.",
            "suggestion": "A clear suggestion on how to fix it."
            """
        },
        {"role": "user", "content": f"My {language}{env_info} code is:\n```{language.lower()}\n{code}\n```\nThe error message is: \"{error_message}\""}
    ]
    try:
        ai_feedback = call_llm(feedback_prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", temperature=0.5, max_tokens=1024)
    except Exception as ai_e:
        print(f"Error generating AI feedback from {DEFAULT_LLM_PROVIDER}: {ai_e}")
        ai_feedback = json.dumps({
            "explanation": f"Could not generate AI feedback for {language} error.",
            "suggestion": "Please check your code syntax and try again."
        })

    response_data = {
        "output": "",
        "raw_error": error_message,
        "ai_feedback": ai_feedback
    }
    
    # Add environment info for JavaScript
    if js_environment:
        response_data["environment"] = js_environment

    return jsonify(response_data), 200


# --- API Routes ---

@app.route('/')
def home():
    """A simple home route to confirm the server is running."""
    return "AI Learning Quest Backend is running with multi-language support and enhanced JavaScript!"

# --- User Registration and Login (unchanged) ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({"message": "Username, email, and password are required"}), 400

    existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
    if existing_user:
        return jsonify({"message": "Username or email already exists"}), 409

    hashed_password = generate_password_hash(password)
    new_user = User(username=username, email=email, password_hash=hashed_password)

    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": "User registered successfully!"}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error during registration: {e}")
        return jsonify({"message": "Registration failed"}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    identifier = data.get('identifier')
    password = data.get('password')

    if not identifier or not password:
        return jsonify({"message": "Identifier (username/email) and password are required"}), 400

    user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"message": "Invalid credentials"}), 401

    return jsonify({"message": "Login successful!", "username": user.username, "email": user.email}), 200


# --- Multi-Language AI Endpoints ---

@app.route('/generate-syllabus', methods=['POST'])
def generate_syllabus():
    data = request.get_json()
    language = data.get('language', 'python')
    domain = data.get('domain', 'programming')
    sub_language = data.get('subLanguage')
    effective_language = data.get('effectiveLanguage', language)
    is_selenium = data.get('isSelenium', False)
    framework = data.get('framework')  # NEW: Framework-specific syllabus generation
    difficulty = data.get('difficulty', 'Medium')
    skill_level = data.get('skillLevel', 'Intermediate')

    if not language:
        return jsonify({"error": "Programming language not provided"}), 400

    # Handle framework-specific syllabus generation
    # Only trigger framework-specific syllabus when explicitly selecting a testing framework
    # AND when domain is specifically testing-related OR when it's a direct framework selection
    is_testing_framework_request = (
        framework and 
        not is_selenium and 
        (domain == 'automation-testing' or domain == 'software-testing' or 
         language in ['pytest', 'unittest', 'TestNG', 'JUnit', 'Mocha', 'Jest', 'NUnit', 'MSTest'])
    )
    
    if is_testing_framework_request:
        # Direct framework selection (e.g., user selected "pytest" or "TestNG" directly)
        framework_language_map = {
            'pytest': 'python',
            'unittest': 'python', 
            'Robot Framework': 'python',
            'TestNG': 'java',
            'JUnit': 'java',
            'Mocha': 'javascript',
            'Jest': 'javascript',
            'NUnit': 'csharp',
            'MSTest': 'csharp'
        }
        
        base_language = framework_language_map.get(framework, language)
        language_display = f"{framework} Testing Framework ({base_language.title()})"
        framework_focus = f"Focus on {framework}-specific testing patterns, best practices, and automation concepts."
        domain_focus = "Software Testing and Automation"
        
    elif is_selenium and sub_language:
        # Selenium with sub-languages and frameworks
        language_display = f"Selenium WebDriver with {sub_language.title()}"
        if framework:
            language_display += f" using {framework}"
            framework_focus = f"Focus on {framework}-specific patterns, best practices, and test organization."
        else:
            framework_focus = "Cover general Selenium WebDriver concepts and basic testing patterns."
        domain_focus = "Web Automation Testing"
    else:
        # Regular programming language
        language_display = language.title()
        framework_focus = ""
        domain_focus = domain.replace('-', ' ').title()

    # Framework-specific syllabus customization
    framework_topics = {
        'pytest': [
            "Pytest fundamentals and fixtures",
            "Parametrized testing and test data",
            "Pytest plugins and configuration",
            "Advanced pytest patterns"
        ],
        'unittest': [
            "Unittest framework basics",
            "Test suites and test discovery",
            "Mocking and test isolation",
            "Unittest best practices"
        ],
        'TestNG': [
            "TestNG annotations and lifecycle",
            "Data providers and parameters",
            "Test groups and dependencies",
            "Parallel execution and reporting"
        ],
        'JUnit': [
            "JUnit 5 fundamentals",
            "Test lifecycle and extensions",
            "Parameterized and dynamic tests",
            "JUnit best practices"
        ],
        'Mocha': [
            "Mocha test structure and hooks",
            "Async testing patterns",
            "Test reporters and configuration",
            "Integration with assertion libraries"
        ],
        'Jest': [
            "Jest testing fundamentals",
            "Mocking and spying",
            "Snapshot testing",
            "Jest configuration and setup"
        ],
        'NUnit': [
            "NUnit attributes and assertions",
            "Test fixtures and setup",
            "Data-driven testing",
            "NUnit advanced features"
        ],
        'Cucumber': [
            "Gherkin syntax and feature files",
            "Step definitions and hooks",
            "Scenario outlines and data tables",
            "Cucumber reporting and integration"
        ]
    }

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are an expert curriculum designer for {difficulty} level programming courses.
            Your task is to generate a comprehensive syllabus for learning "{language_display}" programming.
            
            COURSE DETAILS:
            Language: {language_display}
            Domain focus: {domain_focus}
            Difficulty: {difficulty}
            Skill Level: {skill_level}
            {f"Framework Focus: {framework}" if framework else ""}
            
            SYLLABUS REQUIREMENTS:
            - Provide 8 to 12 main lesson topics, ordered logically for {language_display}
            - Include {domain_focus} specific concepts where relevant
            - Tailor complexity to {difficulty} difficulty level
            - For complex topics, include 3 to 5 subtopics
            {f"- Include {framework}-specific concepts and patterns" if framework else ""}
            {f"- {framework_focus}" if framework_focus else ""}
            
            {f'''FRAMEWORK-SPECIFIC REQUIREMENTS:
            Include these {framework} topics in your syllabus:
            {chr(10).join(f"- {topic}" for topic in framework_topics.get(framework, []))}''' if framework and framework in framework_topics else ''}
            
            DIFFICULTY-SPECIFIC GUIDELINES:
            {f"Easy: Focus on fundamental concepts, simple examples, step-by-step learning" if difficulty == 'Easy' else ""}
            {f"Medium: Balance theory and practice, include real-world examples" if difficulty == 'Medium' else ""}
            {f"Hard: Advanced concepts, complex scenarios, best practices, optimization" if difficulty == 'Hard' else ""}

            Format your response as a JSON object with a single key "syllabus",
            whose value is an array of objects. Each object should have:
            - "title": The main lesson title (string)
            - Optionally, "subtopics": An array of strings for subtopic titles

            Example JSON structure:
            {{
                "syllabus": [
                    {{"title": "Introduction to {language_display}"}},
                    {{"title": "Basic Concepts", "subtopics": ["Variables", "Data Types", "Operators"]}},
                    {{"title": "Control Flow", "subtopics": ["Conditionals", "Loops", "Exception Handling"]}},
                    {f'{{"title": "{framework} Framework Basics"}},' if framework else ""}
                    {{"title": "Advanced Topics"}}
                ]
            }}
            """
        },
        {"role": "user", "content": f"Generate a {difficulty} level syllabus for {language_display} in {domain_focus} domain{f' using {framework} framework' if framework else ''}."}
    ]

    try:
        ai_output = call_llm(prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", max_tokens=2048)
        return ai_output, 200
    except Exception as e:
        print(f"Error generating syllabus content from {DEFAULT_LLM_PROVIDER}: {e}")
        return jsonify({"error": f"Failed to generate syllabus content: {str(e)}"}), 500


@app.route('/generate-lesson', methods=['POST'])
def generate_lesson():
    data = request.get_json()
    concept = data.get('concept', 'Programming basics')
    language = data.get('language', 'python')
    domain = data.get('domain', 'programming')
    sub_language = data.get('subLanguage')
    effective_language = data.get('effectiveLanguage', language)
    is_selenium = data.get('isSelenium', False)
    framework = data.get('framework')  # NEW: Framework-specific context
    
    # *** IMPORTANT FIX: Extract difficulty and skill level ***
    difficulty = data.get('difficulty', 'Medium')
    skill_level = data.get('skillLevel', 'Intermediate')

    if not concept:
        return jsonify({"error": "Concept not provided"}), 400

    # Framework-specific configurations
    framework_configs = {
        # Python Selenium frameworks
        'pytest': {
            'imports': 'import pytest\nfrom selenium import webdriver\nfrom selenium.webdriver.common.by import By',
            'patterns': 'pytest fixtures, test classes, assert statements',
            'setup': '@pytest.fixture for driver setup and teardown',
            'example_focus': 'pytest-specific decorators, fixtures, and parameterization',
            'test_structure': 'class-based tests with fixtures',
            'assertions': 'assert statements',
            'lifecycle': 'setup_method, teardown_method, fixtures'
        },
        'unittest': {
            'imports': 'import unittest\nfrom selenium import webdriver\nfrom selenium.webdriver.common.by import By',
            'patterns': 'unittest.TestCase inheritance, setUp/tearDown methods',
            'setup': 'setUp() and tearDown() methods',
            'example_focus': 'unittest framework structure and assertions',
            'test_structure': 'class inheriting from unittest.TestCase',
            'assertions': 'self.assertEqual, self.assertTrue, self.assertIn',
            'lifecycle': 'setUp, tearDown, setUpClass, tearDownClass'
        },
        'Robot Framework': {
            'imports': '*** Settings ***\nLibrary    SeleniumLibrary',
            'patterns': 'Robot Framework keywords, test cases, variables',
            'setup': 'Suite Setup and Test Setup keywords',
            'example_focus': 'Robot Framework syntax and built-in keywords',
            'test_structure': '*** Test Cases *** section with keywords',
            'assertions': 'Should Be Equal, Should Contain, Element Should Be Visible',
            'lifecycle': 'Suite Setup, Suite Teardown, Test Setup, Test Teardown'
        },
        
        # Java Selenium frameworks
        'TestNG': {
            'imports': 'import org.testng.annotations.*;\nimport org.openqa.selenium.WebDriver;\nimport org.openqa.selenium.chrome.ChromeDriver;',
            'patterns': 'TestNG annotations, DataProvider, parallel execution\'s',
            'setup': '@BeforeMethod and @AfterMethod annotations',
            'example_focus': 'TestNG lifecycle methods, assertions, and data providers',
            'test_structure': 'class with @Test annotated methods',
            'assertions': 'Assert.assertEquals, Assert.assertTrue, Assert.assertNotNull',
            'lifecycle': '@BeforeMethod, @AfterMethod, @BeforeClass, @AfterClass'
        },
        'JUnit': {
            'imports': 'import org.junit.jupiter.api.*;\nimport org.openqa.selenium.WebDriver;\nimport org.openqa.selenium.chrome.ChromeDriver;',
            'patterns': 'JUnit 5 annotations, lifecycle methods, assertions',
            'setup': '@BeforeEach and @AfterEach annotations',
            'example_focus': 'JUnit 5 test structure and modern assertions',
            'test_structure': 'class with @Test annotated methods',
            'assertions': 'Assertions.assertEquals, Assertions.assertTrue, Assertions.assertAll',
            'lifecycle': '@BeforeEach, @AfterEach, @BeforeAll, @AfterAll'
        },
        
        # JavaScript Selenium frameworks
        'Mocha': {
            'imports': 'const { Builder, By, until } = require("selenium-webdriver");\nconst assert = require("assert");',
            'patterns': 'describe/it blocks, async/await, chai assertions',
            'setup': 'beforeEach and afterEach hooks',
            'example_focus': 'JavaScript async patterns with Selenium WebDriver',
            'test_structure': 'describe blocks with it test cases',
            'assertions': 'assert.strictEqual, assert.ok, chai expect syntax',
            'lifecycle': 'before, after, beforeEach, afterEach hooks'
        },
        'Jest': {
            'imports': 'const { Builder, By, until } = require("selenium-webdriver");\nconst { expect } = require("@jest/globals");',
            'patterns': 'Jest test suites, mocking, snapshot testing',
            'setup': 'beforeEach and afterEach Jest hooks',
            'example_focus': 'Jest-specific matchers and async testing',
            'test_structure': 'describe blocks with test() functions',
            'assertions': 'expect().toBe(), expect().toEqual(), Jest matchers',
            'lifecycle': 'beforeAll, afterAll, beforeEach, afterEach'
        },
        
        # C# Selenium frameworks
        'NUnit': {
            'imports': 'using NUnit.Framework;\nusing OpenQA.Selenium;\nusing OpenQA.Selenium.Chrome;',
            'patterns': 'NUnit attributes, test fixtures, assertions',
            'setup': '[SetUp] and [TearDown] attributes',
            'example_focus': 'NUnit test structure and fluent assertions',
            'test_structure': '[TestFixture] class with [Test] methods',
            'assertions': 'Assert.That(), Assert.AreEqual(), fluent assertions',
            'lifecycle': '[OneTimeSetUp], [OneTimeTearDown], [SetUp], [TearDown]'
        },
        'MSTest': {
            'imports': 'using Microsoft.VisualStudio.TestTools.UnitTesting;\nusing OpenQA.Selenium;\nusing OpenQA.Selenium.Chrome;',
            'patterns': 'MSTest attributes, test initialization',
            'setup': '[TestInitialize] and [TestCleanup] attributes',
            'example_focus': 'MSTest framework structure and assertions',
            'test_structure': '[TestClass] with [TestMethod] methods',
            'assertions': 'Assert.AreEqual(), Assert.IsTrue(), Assert.IsNotNull()',
            'lifecycle': '[ClassInitialize], [ClassCleanup], [TestInitialize], [TestCleanup]'
        },
        'Cucumber': {
            'imports': 'import io.cucumber.java.en.Given;\nimport io.cucumber.java.en.When;\nimport io.cucumber.java.en.Then;\nimport org.junit.Assert;',
            'patterns': 'Gherkin syntax, step definitions, feature files',
            'setup': '@Given, @When, @Then annotations',
            'example_focus': 'BDD approach with Gherkin scenarios and step definitions',
            'test_structure': 'Feature files with Scenario outlines and step definitions',
            'assertions': 'Assert.assertEquals, Assert.assertTrue, custom assertions',
            'lifecycle': '@Before, @After hooks, scenario lifecycle'
        }
    }

    # Determine the effective language and framework context
    if is_selenium and sub_language:
        example_language = sub_language
        language_context = f"Selenium WebDriver automation using {sub_language.title()}"
        code_type = f"{sub_language} with Selenium WebDriver"
        
        # Get framework-specific configuration
        framework_info = framework_configs.get(framework, {}) if framework else {}
        framework_context = f" with {framework} framework" if framework else ""
        language_context += framework_context
        
        # Use framework-specific imports or fallback to basic Selenium
        if framework and framework_info:
            import_statement = framework_info.get('imports', '')
            framework_patterns = framework_info.get('patterns', '')
            framework_setup = framework_info.get('setup', '')
            framework_focus = framework_info.get('example_focus', '')
            test_structure = framework_info.get('test_structure', '')
            assertion_style = framework_info.get('assertions', '')
            lifecycle_methods = framework_info.get('lifecycle', '')
        else:
            # Fallback to basic Selenium imports
            framework_info = SUPPORTED_LANGUAGES['selenium']['sub_languages'].get(sub_language, {})
            import_statement = framework_info.get('imports', '')
            framework_patterns = f"basic {sub_language} Selenium patterns"
            framework_setup = "basic WebDriver setup and teardown"
            framework_focus = f"fundamental {sub_language} Selenium concepts"
            test_structure = f"basic {sub_language} test structure"
            assertion_style = f"standard {sub_language} assertions"
            lifecycle_methods = f"manual driver lifecycle management"
    else:
        example_language = language
        language_context = f"{language.title()} programming"
        code_type = language.title()
        framework_info = {}  # Initialize framework_info to avoid UnboundLocalError
        import_statement = ""
        framework_patterns = ""
        framework_setup = ""
        framework_focus = ""
        test_structure = ""
        assertion_style = ""
        lifecycle_methods = ""

    # *** IMPORTANT FIX: Create difficulty-specific instructions ***
    difficulty_instructions = {
        'Easy': {
            'level_description': 'absolute beginner level',
            'code_complexity': 'very simple, basic concepts only',
            'concepts_to_avoid': 'Avoid complex imports, classes, advanced functions, servers, networking, or multi-threading',
            'preferred_concepts': 'Use basic variables, simple functions, print statements, basic math, strings, and lists',
            'max_lines': '10-15 lines maximum'
        },
        'Medium': {
            'level_description': 'intermediate level',
            'code_complexity': 'moderate complexity with some advanced concepts',
            'concepts_to_avoid': 'Avoid overly complex architectures or advanced design patterns',
            'preferred_concepts': 'Can include functions, loops, conditionals, basic classes, and simple imports',
            'max_lines': '20-30 lines'
        },
        'Hard': {
            'level_description': 'advanced level',
            'code_complexity': 'complex concepts and real-world applications',
            'concepts_to_avoid': 'No restrictions',
            'preferred_concepts': 'Can include complex classes, design patterns, advanced libraries, networking, etc.',
            'max_lines': '30+ lines'
        }
    }
    
    current_difficulty = difficulty_instructions.get(difficulty, difficulty_instructions['Medium'])

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are an expert, friendly, and patient {language_context} instructor.
            Your sole purpose is to explain a programming concept to learners and provide an appropriate code example.
            
            DIFFICULTY LEVEL: {difficulty} ({current_difficulty['level_description']})
            SKILL LEVEL: {skill_level}
            Language: {language_context}
            Domain focus: {domain.replace('-', ' ').title()}
            {f"Framework: {framework} - {framework_focus}" if framework and framework_focus else ""}
            
            IMPORTANT DIFFICULTY GUIDELINES:
            - Code complexity: {current_difficulty['code_complexity']}
            - {current_difficulty['concepts_to_avoid']}
            - {current_difficulty['preferred_concepts']}
            - Code length: {current_difficulty['max_lines']}
            
            {f'''FRAMEWORK-SPECIFIC REQUIREMENTS ({framework}):
            - Test Structure: {test_structure}
            - Imports: {import_statement}
            - Patterns: {framework_patterns}
            - Setup/Teardown: {framework_setup}
            - Assertions: {assertion_style}
            - Lifecycle: {lifecycle_methods}
            - Focus: {framework_focus}''' if framework and framework_info else ''}
            
            You MUST respond with a JSON object. Do NOT include any conversational filler, greetings, or additional text outside the JSON.
            The JSON structure must be:
            {{
                "explanation": "A multi-line string containing the explanation points for {language_context} at {difficulty} difficulty level{f' using {framework} framework patterns' if framework else ''}.",
                "code_example": "A multi-line string containing the {code_type} code example appropriate for {difficulty} difficulty{f' following {framework} framework conventions' if framework else ''}."
            }}
            
            For the code example:
            - Use {example_language} syntax
            {f"- Use {framework} framework structure and patterns" if framework else ""}
            {f"- Include proper imports: {import_statement}" if import_statement else ""}
            {f"- Follow {framework} best practices for {framework_patterns}" if framework_patterns else ""}
            {f"- Use {assertion_style} for validations" if assertion_style else ""}
            {f"- Include proper {lifecycle_methods} for test lifecycle" if lifecycle_methods else ""}
            - Make it appropriate for {difficulty} difficulty level
            - Include comments explaining key parts
            - Focus on {domain.replace('-', ' ')} concepts where relevant
            - STRICTLY follow the difficulty guidelines above
            {f"- Demonstrate {framework}-specific features and best practices" if framework else ""}
            
            Ensure the JSON is perfectly valid and complete.
            **IMPORTANT:** For the 'code_example' value, ensure the code is formatted as a standard string.
            DO NOT use triple quotes (''' or \"\"\") within the 'code_example' string, as this invalidates the JSON.
            Escape any internal double quotes if necessary (e.g., use \\" instead of ").
            """
        },
        {"role": "user", "content": f"Explain \"{concept}\" in {language_context} with a code example suitable for {difficulty} difficulty level ({skill_level} skill level){f' using {framework} framework' if framework else ''}."}
    ]

    try:
        ai_output = call_llm(prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", max_tokens=1024)
        
        # Parse the AI response JSON and return as proper Flask response
        try:
            import json
            parsed_response = json.loads(ai_output)
            return jsonify(parsed_response), 200
        except json.JSONDecodeError as json_err:
            print(f"Error parsing AI response JSON: {json_err}")
            print(f"Raw AI response: {ai_output}")
            # Fallback response if AI doesn't return valid JSON
            return jsonify({
                "explanation": f"This lesson covers: {concept}",
                "code_example": f"# {concept} example\n# Your code here"
            }), 200
    except Exception as e:
        print(f"Error generating lesson content from {DEFAULT_LLM_PROVIDER}: {e}")
        return jsonify({"error": f"Failed to generate lesson content: {str(e)}"}), 500


@app.route('/explain-code', methods=['POST'])
def explain_code():
    data = request.get_json()
    code = data.get('code', '')
    language = data.get('language', 'python')
    difficulty = data.get('difficulty', 'Medium')
    skill_level = data.get('skillLevel', 'Intermediate')
    concept = data.get('concept', 'Programming code')

    if not code.strip():
        return jsonify({"error": "Code not provided"}), 400

    # Create difficulty-specific explanation styles
    explanation_styles = {
        'Easy': {
            'tone': 'very simple and friendly',
            'detail_level': 'basic, step-by-step',
            'vocabulary': 'simple words, avoid technical jargon',
            'examples': 'relate to everyday concepts',
            'focus': 'what each line does in plain English'
        },
        'Medium': {
            'tone': 'clear and informative',
            'detail_level': 'moderate detail with some technical terms',
            'vocabulary': 'balance of simple and technical terms',
            'examples': 'programming-related analogies',
            'focus': 'how the code works and why'
        },
        'Hard': {
            'tone': 'technical and comprehensive',
            'detail_level': 'detailed analysis with advanced concepts',
            'vocabulary': 'full technical terminology',
            'examples': 'complex programming patterns and best practices',
            'focus': 'deep understanding of logic, patterns, and optimization'
        }
    }

    current_style = explanation_styles.get(difficulty, explanation_styles['Medium'])

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are a patient and expert {language.title()} programming instructor. 
            Your task is to explain code in a way that's perfect for a {difficulty} difficulty level ({skill_level} skill level) learner.

            EXPLANATION STYLE FOR {difficulty} LEVEL:
            - Tone: {current_style['tone']}
            - Detail level: {current_style['detail_level']}
            - Vocabulary: {current_style['vocabulary']}
            - Examples: {current_style['examples']}
            - Focus: {current_style['focus']}

            You MUST respond with a JSON object containing:
            {{
                "explanation": "A detailed explanation of the code appropriate for {difficulty} level",
                "line_by_line": "A line-by-line breakdown if helpful for this difficulty level",
                "key_concepts": "Main programming concepts demonstrated in this code",
                "difficulty_notes": "Any notes specific to {difficulty} level learners"
            }}

            For {difficulty} level:
            - {"Use very simple language, explain every small step, relate to real-world examples" if difficulty == 'Easy' else ""}
            - {"Use moderate technical terms, explain the logic and flow" if difficulty == 'Medium' else ""}
            - {"Use full technical terminology, discuss patterns, efficiency, and best practices" if difficulty == 'Hard' else ""}

            Make sure the explanation is encouraging and builds confidence for {difficulty} level learners.
            """
        },
        {
            "role": "user", 
            "content": f"Please explain this {language} code for a {difficulty} level learner working on '{concept}':\n\n{code}"
        }
    ]

    try:
        ai_output = call_llm(prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", max_tokens=1500)
        
        try:
            import json
            parsed_response = json.loads(ai_output)
            return jsonify(parsed_response), 200
        except json.JSONDecodeError as json_err:
            print(f"Error parsing AI explanation response JSON: {json_err}")
            print(f"Raw AI response: {ai_output}")
            # Fallback response
            return jsonify({
                "explanation": f"This {language} code demonstrates: {concept}",
                "line_by_line": "Line-by-line explanation not available",
                "key_concepts": f"Basic {language} programming concepts",
                "difficulty_notes": f"This explanation is tailored for {difficulty} level"
            }), 200
    except Exception as e:
        print(f"Error generating code explanation from {DEFAULT_LLM_PROVIDER}: {e}")
        return jsonify({"error": f"Failed to generate code explanation: {str(e)}"}), 500


@app.route('/chat-with-ai', methods=['POST'])
def chat_with_ai():
    data = request.get_json()
    user_message = data.get('message')
    language = data.get('language', 'python')
    domain = data.get('domain', 'programming')
    sub_language = data.get('subLanguage')
    effective_language = data.get('effectiveLanguage', language)
    is_selenium = data.get('isSelenium', False)
    framework = data.get('framework')  # NEW: Framework context for AI chat

    if not user_message:
        return jsonify({"response": "Please provide a message to chat with the AI."}), 400

    # Determine context with framework awareness
    if is_selenium and sub_language:
        context = f"Selenium WebDriver automation using {sub_language.title()}"
        if framework:
            context += f" with {framework} framework"
            framework_context = f"I am an expert in {framework} testing framework with Selenium WebDriver in {sub_language.title()}."
        else:
            framework_context = f"I am an expert in Selenium WebDriver automation using {sub_language.title()}."
    else:
        context = f"{language.title()} programming"
        framework_context = f"I am an expert in {language.title()} programming."

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are AI Sensei, a friendly {context} tutor.
            {framework_context}
            Provide concise, direct, and helpful answers to beginner programming questions.
            
            Current context:
            - Language: {context}
            - Domain: {domain.replace('-', ' ').title()}
            {f"- Framework: {framework}" if framework else ""}
            
            Focus on {domain.replace('-', ' ')} concepts when relevant.
            When providing code examples, use {sub_language if is_selenium and sub_language else language} syntax.
            {f"Include {framework}-specific patterns and best practices when applicable." if framework else ""}
            {f"Include Selenium WebDriver concepts and {framework} testing patterns when applicable." if is_selenium and framework else ""}
            {f"Include general Selenium WebDriver concepts when applicable." if is_selenium and not framework else ""}
            Do not include internal thoughts or instructions in your response.
            """
        },
        {"role": "user", "content": user_message}
    ]

    try:
        raw_ai_response_text = call_llm(
            prompt_messages,
            DEFAULT_LLM_PROVIDER,
            temperature=0.5,
            max_tokens=1500
        )

        # Post-processing to remove internal thoughts
        cleaned_response_text = raw_ai_response_text

        # Remove <think>...</think> tags and their content
        cleaned_response_text = re.sub(r'<think>.*?</think>', '', cleaned_response_text, flags=re.DOTALL | re.IGNORECASE)
        cleaned_response_text = re.sub(r'\[THINKING\].*?\[/THINKING\]', '', cleaned_response_text, flags=re.DOTALL | re.IGNORECASE)
        cleaned_response_text = re.sub(r'\(Internal thought\).*?\)', '', cleaned_response_text, flags=re.DOTALL | re.IGNORECASE)
        
        cleaned_response_text = cleaned_response_text.strip()

        if not cleaned_response_text:
            cleaned_response_text = f"I'm here to help with {context}! What would you like to learn today?"

        return jsonify({"response": cleaned_response_text}), 200
    except Exception as e:
        print(f"Error chatting with AI from {DEFAULT_LLM_PROVIDER}: {e}")
        return jsonify({"response": f"I'm sorry, I encountered an error and cannot answer your question right now: {str(e)}"}), 500


@app.route('/run-code', methods=['POST'])
def run_code():
    data = request.get_json()
    code_to_run = data.get('code', '')
    language = data.get('language', 'python')
    sub_language = data.get('subLanguage')
    effective_language = data.get('effectiveLanguage', language)
    is_selenium = data.get('isSelenium', False)
    framework = data.get('framework')  # NEW: Framework-specific execution

    if not code_to_run:
        return jsonify({"output": "", "raw_error": "No code provided", "ai_feedback": ""}), 400

    # Determine execution language and framework context
    exec_language = sub_language if is_selenium and sub_language else language

    print(f"Executing {exec_language} code{f' with {framework} framework' if framework else ''}...")

    # Framework-specific execution for Selenium
    if is_selenium and framework and sub_language:
        return execute_selenium_framework_code(code_to_run, sub_language, framework)
    elif exec_language == 'python':
        return execute_python_code(code_to_run)
    elif exec_language == 'javascript':
        return execute_javascript_code(code_to_run)
    elif exec_language == 'java':
        return execute_java_code(code_to_run)
    elif exec_language == 'csharp':
        return execute_csharp_code(code_to_run)
    else:
        return jsonify({
            "output": "",
            "raw_error": f"Code execution not yet fully supported for {exec_language}",
            "ai_feedback": json.dumps({
                "explanation": f"Code execution for {exec_language} is implemented but may require additional setup.",
                "suggestion": f"Make sure you have the {exec_language} runtime/compiler installed. For now, you can copy the code to your local {exec_language} environment."
            })
        }), 200


def execute_selenium_framework_code(code_to_run, language, framework):
    """Execute Selenium code with framework-specific handling"""
    
    framework_execution = {
        'pytest': execute_pytest_code,
        'unittest': execute_unittest_code,
        'TestNG': execute_testng_code,
        'JUnit': execute_junit_code,
        'Mocha': execute_mocha_code,
        'Jest': execute_jest_code,
        'NUnit': execute_nunit_code,
        'MSTest': execute_mstest_code,
        'Cucumber': execute_cucumber_code
    }
    
    executor = framework_execution.get(framework)
    if executor:
        return executor(code_to_run, language)
    else:
        # Fallback to standard execution
        if language == 'python':
            return execute_python_code(code_to_run)
        elif language == 'java':
            return execute_java_code(code_to_run)
        elif language == 'javascript':
            return execute_javascript_code(code_to_run)
        elif language == 'csharp':
            return execute_csharp_code(code_to_run)
        else:
            return jsonify({
                "output": "",
                "raw_error": f"Unsupported language: {language}",
                "ai_feedback": json.dumps({
                    "explanation": f"Execution for {language} with {framework} is not yet supported.",
                    "suggestion": f"Try running this code in your local {framework} environment."
                })
            }), 200


def execute_pytest_code(code_to_run, language='python'):
    """Execute Python code with pytest framework"""
    try:
        # Check if pytest is available
        pytest_check = subprocess.run(['python', '-c', 'import pytest; print(pytest.__version__)'], 
                                     capture_output=True, text=True, timeout=10)
        
        if pytest_check.returncode != 0:
            return jsonify({
                "output": "",
                "raw_error": "pytest not installed",
                "ai_feedback": json.dumps({
                    "explanation": "pytest framework is not installed in the environment.",
                    "suggestion": "Install pytest using: pip install pytest"
                })
            }), 200
        
        # Create a temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='_test.py', delete=False) as temp_file:
            temp_file.write(code_to_run)
            temp_file_path = temp_file.name
        
        try:
            # Run pytest on the temporary file
            result = subprocess.run(['python', '-m', 'pytest', temp_file_path, '-v'], 
                                  capture_output=True, text=True, timeout=30)
            
            output = result.stdout
            error = result.stderr
            
            if result.returncode == 0:
                return jsonify({
                    "output": output,
                    "raw_error": "",
                    "ai_feedback": json.dumps({
                        "explanation": "pytest execution completed successfully!",
                        "suggestion": "All tests passed. Great job with your pytest code!"
                    })
                }), 200
            else:
                return jsonify({
                    "output": output,
                    "raw_error": error,
                    "ai_feedback": json.dumps({
                        "explanation": "pytest found some issues with your test code.",
                        "suggestion": "Check the test output for specific failures and fix the assertions or test logic."
                    })
                }), 200
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except subprocess.TimeoutExpired:
        return jsonify({
            "output": "",
            "raw_error": "pytest execution timed out",
            "ai_feedback": json.dumps({
                "explanation": "Your pytest code took too long to execute.",
                "suggestion": "Check for infinite loops or long-running operations in your tests."
            })
        }), 200
    except Exception as e:
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "Error running pytest code.",
                "suggestion": "Check your pytest syntax and imports."
            })
        }), 200


def execute_cucumber_code(code_to_run, language='java'):
    """Execute Cucumber BDD framework code with Java"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create basic Maven project structure for Cucumber
            pom_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>cucumber-test</artifactId>
    <version>1.0-SNAPSHOT</version>

    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>

    <dependencies>
        <dependency>
            <groupId>io.cucumber</groupId>
            <artifactId>cucumber-java</artifactId>
            <version>7.15.0</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>io.cucumber</groupId>
            <artifactId>cucumber-junit</artifactId>
            <version>7.15.0</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>junit</groupId>
            <artifactId>junit</artifactId>
            <version>4.13.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>'''

            # Create directory structure
            src_dir = os.path.join(temp_dir, 'src', 'test', 'java')
            os.makedirs(src_dir, exist_ok=True)
            resources_dir = os.path.join(temp_dir, 'src', 'test', 'resources')
            os.makedirs(resources_dir, exist_ok=True)

            # Write pom.xml
            with open(os.path.join(temp_dir, 'pom.xml'), 'w') as f:
                f.write(pom_xml)

            # Write the Cucumber code
            with open(os.path.join(src_dir, 'CucumberTest.java'), 'w') as f:
                f.write(code_to_run)

            # Try to compile and run with Maven
            try:
                # Compile
                compile_result = subprocess.run(
                    ['mvn', 'compile', 'test-compile'],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if compile_result.returncode != 0:
                    return generate_error_feedback(code_to_run, compile_result.stderr, 'Cucumber')

                # Run tests
                test_result = subprocess.run(
                    ['mvn', 'test'],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if test_result.returncode == 0:
                    return jsonify({
                        "output": test_result.stdout,
                        "raw_error": "",
                        "ai_feedback": ""
                    }), 200
                else:
                    return generate_error_feedback(code_to_run, test_result.stderr, 'Cucumber')

            except FileNotFoundError:
                # Fallback: try to compile and run manually if Maven not available
                return jsonify({
                    "output": "",
                    "raw_error": "Maven not found. Please install Maven to run Cucumber tests.",
                    "ai_feedback": json.dumps({
                        "explanation": "Maven is required to compile and run Cucumber tests.",
                        "suggestion": "Install Apache Maven and ensure it's in your PATH."
                    })
                }), 200

    except subprocess.TimeoutExpired:
        return jsonify({
            "output": "",
            "raw_error": "Code execution timed out",
            "ai_feedback": json.dumps({
                "explanation": "Your Cucumber test took too long to compile or execute.",
                "suggestion": "Check for infinite loops or optimize your test scenarios."
            })
        }), 200
    except Exception as e:
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "An unexpected error occurred during Cucumber execution.",
                "suggestion": "Please check your Gherkin syntax and step definitions."
            })
        }), 200


def execute_unittest_code(code_to_run, language='python'):
    """Execute Python code with unittest framework"""
    try:
        # Create a temporary test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='_test.py', delete=False) as temp_file:
            temp_file.write(code_to_run)
            temp_file_path = temp_file.name
        
        try:
            # Run unittest on the temporary file
            result = subprocess.run(['python', '-m', 'unittest', temp_file_path.replace('.py', ''), '-v'], 
                                  capture_output=True, text=True, timeout=30)
            
            output = result.stdout
            error = result.stderr
            
            return jsonify({
                "output": output,
                "raw_error": error,
                "ai_feedback": json.dumps({
                    "explanation": "unittest execution completed.",
                    "suggestion": "Check the test results above for any failures or errors."
                })
            }), 200
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({
            "output": "",
            "raw_error": str(e),
            "ai_feedback": json.dumps({
                "explanation": "Error running unittest code.",
                "suggestion": "Check your unittest syntax and class structure."
            })
        }), 200


def execute_testng_code(code_to_run, language='java'):
    """Execute Java code with TestNG framework"""
    return jsonify({
        "output": "TestNG execution simulation",
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "TestNG framework execution is simulated.",
            "suggestion": "To run TestNG tests, compile and execute in your local Java environment with TestNG dependencies."
        })
    }), 200


def execute_junit_code(code_to_run, language='java'):
    """Execute Java code with JUnit framework"""
    return jsonify({
        "output": "JUnit execution simulation",
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "JUnit framework execution is simulated.",
            "suggestion": "To run JUnit tests, compile and execute in your local Java environment with JUnit 5 dependencies."
        })
    }), 200


def execute_mocha_code(code_to_run, language='javascript'):
    """Execute JavaScript code with Mocha framework"""
    return jsonify({
        "output": "Mocha execution simulation",
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "Mocha framework execution is simulated.",
            "suggestion": "To run Mocha tests, use 'npm test' or 'mocha' command in your local Node.js environment."
        })
    }), 200


def execute_jest_code(code_to_run, language='javascript'):
    """Execute JavaScript code with Jest framework"""
    return jsonify({
        "output": "Jest execution simulation", 
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "Jest framework execution is simulated.",
            "suggestion": "To run Jest tests, use 'npm test' command in your local Node.js environment with Jest configured."
        })
    }), 200


def execute_nunit_code(code_to_run, language='csharp'):
    """Execute C# code with NUnit framework"""
    return jsonify({
        "output": "NUnit execution simulation",
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "NUnit framework execution is simulated.",
            "suggestion": "To run NUnit tests, compile and execute in your local .NET environment with NUnit packages."
        })
    }), 200


def execute_mstest_code(code_to_run, language='csharp'):
    """Execute C# code with MSTest framework"""
    return jsonify({
        "output": "MSTest execution simulation",
        "raw_error": "",
        "ai_feedback": json.dumps({
            "explanation": "MSTest framework execution is simulated.",
            "suggestion": "To run MSTest tests, use 'dotnet test' command in your local .NET environment."
        })
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint with enhanced features info"""
    return jsonify({
        'status': 'healthy',
        'service': 'AI Learning Quest Backend',
        'features': {
            'multi_language_support': True,
            'javascript_execution': True,
            'javascript_html_support': True,
            'browser_simulation': True,
            'environment_detection': True,
            'python_execution': True,
            'java_execution': True,
            'csharp_execution': True,
            'selenium_support': True
        },
        'supported_languages': list(SUPPORTED_LANGUAGES.keys()),
        'llm_provider': DEFAULT_LLM_PROVIDER
    })


if __name__ == '__main__':
    # Create database tables
    with app.app_context():
        db.create_all()

    print("Starting AI Learning Quest Backend with enhanced multi-language support...")
    print(f"Supported languages: {', '.join(SUPPORTED_LANGUAGES.keys())}")
    print(f"Default LLM Provider: {DEFAULT_LLM_PROVIDER}")
    print("✅ Enhanced JavaScript execution with HTML support enabled!")
    print("✅ Browser API simulation enabled!")
    print("✅ Environment detection enabled!")
    
    app.run(debug=True, port=5002)
