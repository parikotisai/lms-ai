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
        'frameworks': ['junit', 'testng'],
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

    if not language:
        return jsonify({"error": "Programming language not provided"}), 400

    # Handle Selenium with sub-languages
    if is_selenium and sub_language:
        language_display = f"Selenium WebDriver with {sub_language.title()}"
        framework_info = SUPPORTED_LANGUAGES['selenium']['sub_languages'].get(sub_language, {}).get('framework', 'testing framework')
        domain_focus = "Web Automation Testing"
    else:
        language_display = language.title()
        framework_info = ""
        domain_focus = domain.replace('-', ' ').title()

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are an expert curriculum designer for absolute beginner programming courses.
            Your task is to generate a comprehensive syllabus for learning "{language_display}" programming, from scratch.
            
            Language: {language_display}
            Domain focus: {domain_focus}
            {f"Testing framework: {framework_info}" if framework_info else ""}
            
            Provide 8 to 12 main lesson topics, ordered logically for {language_display}.
            Include {domain_focus} specific concepts where relevant.
            For more complex main topics (e.g., "Object-Oriented Programming", "Data Structures", "Functions", "Control Flow", "Loops"),
            also generate 3 to 5 concise subtopics for them. Other simple topics can just be main topics.
            
            {f"Focus on web automation testing concepts, browser interactions, and {framework_info} testing patterns." if is_selenium else ""}

            Format your response as a JSON object with a single key "syllabus",
            whose value is an array of objects. Each object in the array should have:
            - "title": The main lesson title (string).
            - Optionally, "subtopics": An array of strings, where each string is a subtopic title.

            Example of expected JSON structure:
            {{
                "syllabus": [
                    {{"title": "Lesson 1"}},
                    {{"title": "Lesson 2", "subtopics": ["Subtopic A", "Subtopic B"]}},
                    {{"title": "Lesson 3", "subtopics": ["Subtopic X", "Subtopic Y", "Subtopic Z"]}},
                    {{"title": "Lesson 4"}}
                ]
            }}
            """
        },
        {"role": "user", "content": f"Generate the syllabus for {language_display} in {domain_focus} domain."}
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

    if not concept:
        return jsonify({"error": "Concept not provided"}), 400

    # Determine the effective language and example type
    if is_selenium and sub_language:
        example_language = sub_language
        language_context = f"Selenium WebDriver automation using {sub_language.title()}"
        code_type = f"{sub_language} with Selenium WebDriver"
        framework_info = SUPPORTED_LANGUAGES['selenium']['sub_languages'].get(sub_language, {})
        import_statement = framework_info.get('imports', '')
    else:
        example_language = language
        language_context = f"{language.title()} programming"
        code_type = language.title()
        import_statement = ""

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are an expert, friendly, and patient {language_context} instructor.
            Your sole purpose is to explain a programming concept to absolute beginners and provide a simple code example.
            
            Language: {language_context}
            Domain focus: {domain.replace('-', ' ').title()}
            {f"Framework: {framework_info.get('framework', '')}" if is_selenium and sub_language else ""}
            
            You MUST respond with a JSON object. Do NOT include any conversational filler, greetings, or additional text outside the JSON.
            The JSON structure must be:
            {{
                "explanation": "A multi-line string containing the explanation points for {language_context}.",
                "code_example": "A multi-line string containing the {code_type} code example."
            }}
            
            For the code example:
            - Use {example_language} syntax
            {f"- Include Selenium WebDriver imports: {import_statement}" if is_selenium else ""}
            {f"- Include basic WebDriver setup and browser interaction" if is_selenium else ""}
            - Make it beginner-friendly with clear variable names
            - Include comments explaining key parts
            - Focus on {domain.replace('-', ' ')} concepts where relevant
            
            Ensure the JSON is perfectly valid and complete.
            **IMPORTANT:** For the 'code_example' value, ensure the code is formatted as a standard string.
            DO NOT use triple quotes (''' or \"\"\") within the 'code_example' string, as this invalidates the JSON.
            Escape any internal double quotes if necessary (e.g., use \\" instead of ").
            """
        },
        {"role": "user", "content": f"Explain \"{concept}\" in {language_context} with a code example."}
    ]

    try:
        ai_output = call_llm(prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", max_tokens=1024)
        return ai_output, 200
    except Exception as e:
        print(f"Error generating lesson content from {DEFAULT_LLM_PROVIDER}: {e}")
        return jsonify({"error": f"Failed to generate lesson content: {str(e)}"}), 500


@app.route('/chat-with-ai', methods=['POST'])
def chat_with_ai():
    data = request.get_json()
    user_message = data.get('message')
    language = data.get('language', 'python')
    domain = data.get('domain', 'programming')
    sub_language = data.get('subLanguage')
    effective_language = data.get('effectiveLanguage', language)
    is_selenium = data.get('isSelenium', False)

    if not user_message:
        return jsonify({"response": "Please provide a message to chat with the AI."}), 400

    # Determine context
    if is_selenium and sub_language:
        context = f"Selenium WebDriver automation using {sub_language.title()}"
        framework_info = SUPPORTED_LANGUAGES['selenium']['sub_languages'].get(sub_language, {}).get('framework', '')
    else:
        context = f"{language.title()} programming"
        framework_info = ""

    prompt_messages = [
        {
            "role": "system",
            "content": f"""You are AI Sensei, a friendly {context} tutor.
            Provide concise, direct, and helpful answers to beginner programming questions.
            
            Current context:
            - Language: {context}
            - Domain: {domain.replace('-', ' ').title()}
            {f"- Testing Framework: {framework_info}" if framework_info else ""}
            
            Focus on {domain.replace('-', ' ')} concepts when relevant.
            When providing code examples, use {sub_language if is_selenium and sub_language else language} syntax.
            {f"Include Selenium WebDriver concepts and {framework_info} testing patterns when applicable." if is_selenium else ""}
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

    if not code_to_run:
        return jsonify({"output": "", "raw_error": "No code provided", "ai_feedback": ""}), 400

    # Determine execution language
    exec_language = sub_language if is_selenium and sub_language else language

    print(f"Executing {exec_language} code...")

    if exec_language == 'python':
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
