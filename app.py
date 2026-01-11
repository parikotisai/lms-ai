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

app = Flask(__name__, static_folder=None, template_folder=None)

# CORS configuration - Allow specific origins for security
# In production, this will only allow your LMS API server to access the AI service
allowed_origins = [
    'http://localhost:5010',      # Local API server
    'http://127.0.0.1:5010',      # Local API server (alternative)
    'http://localhost:5173',      # Local frontend (for direct testing)
    'https://lms.bytesfersolutions.com',  # Production frontend
    'http://lms.bytesfersolutions.com'    # Production frontend (HTTP)
]

# Add custom origin from environment if provided
frontend_url = os.getenv('FRONTEND_URL')
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

CORS(app, origins=allowed_origins, supports_credentials=True)

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


# --- Progressive Learning Configuration ---
DIFFICULTY_LESSON_PROGRESSION = {
    'Easy': {
        'lessons_1_3': {
            'allowed_concepts': ['print', 'comments', 'hello world', 'basic output'],
            'avoid': ['functions', 'classes', 'imports', 'loops', 'conditionals', 'variables'],
            'max_lines': 5,
            'example_type': 'hello_world'
        },
        'lessons_4_6': {
            'allowed_concepts': ['variables', 'assignment', 'data types', 'basic math'],
            'avoid': ['functions', 'classes', 'imports', 'loops', 'conditionals'],
            'max_lines': 8,
            'example_type': 'variables_and_types'
        },
        'lessons_7_10': {
            'allowed_concepts': ['conditionals', 'if-else', 'comparison', 'basic loops'],
            'avoid': ['functions', 'classes', 'imports', 'complex loops'],
            'max_lines': 12,
            'example_type': 'simple_control_flow'
        },
        'lessons_11_15': {
            'allowed_concepts': ['simple functions', 'basic loops', 'lists', 'strings'],
            'avoid': ['classes', 'complex imports', 'advanced concepts'],
            'max_lines': 15,
            'example_type': 'basic_functions'
        },
        'lessons_16_plus': {
            'allowed_concepts': ['all basic concepts'],
            'avoid': ['advanced OOP', 'decorators', 'generators'],
            'max_lines': 20,
            'example_type': 'intermediate_basics'
        }
    },
    'Medium': {
        'lessons_1_3': {
            'allowed_concepts': ['functions', 'basic program structure', 'imports'],
            'avoid': ['complex classes', 'decorators', 'generators'],
            'max_lines': 15,
            'example_type': 'function_basics'
        },
        'lessons_4_8': {
            'allowed_concepts': ['functions', 'loops', 'conditionals', 'data structures'],
            'avoid': ['complex OOP', 'decorators', 'advanced patterns'],
            'max_lines': 25,
            'example_type': 'intermediate_programming'
        },
        'lessons_9_plus': {
            'allowed_concepts': ['classes', 'file I/O', 'error handling', 'modules'],
            'avoid': ['decorators', 'metaclasses', 'advanced patterns'],
            'max_lines': 35,
            'example_type': 'intermediate_advanced'
        }
    },
    'Hard': {
        'lessons_1_3': {
            'allowed_concepts': ['OOP', 'design patterns', 'architecture'],
            'avoid': [],
            'max_lines': 40,
            'example_type': 'advanced_concepts'
        },
        'lessons_4_plus': {
            'allowed_concepts': ['all concepts', 'advanced patterns', 'optimization'],
            'avoid': [],
            'max_lines': 50,
            'example_type': 'expert_level'
        }
    }
}


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


# --- Progressive Learning Helper Functions ---
def extract_lesson_number(concept):
    """
    Extract lesson number from concept title
    Examples: "Lesson 1: Introduction" -> 1, "Introduction to Python" -> 1
    """
    import re
    # Try to match "Lesson X:" pattern
    match = re.search(r'[Ll]esson\s+(\d+)', concept)
    if match:
        return int(match.group(1))
    
    # Check if it's an introduction (assume Lesson 1)
    if 'introduction' in concept.lower() or 'intro to' in concept.lower():
        return 1
    
    # Default to lesson 1 if we can't determine
    return 1


def get_lesson_constraints(difficulty, lesson_number):
    """
    Get appropriate content constraints based on difficulty and lesson number
    """
    progression = DIFFICULTY_LESSON_PROGRESSION.get(difficulty, DIFFICULTY_LESSON_PROGRESSION['Medium'])
    
    # Determine which lesson range this falls into
    if lesson_number <= 3:
        key = 'lessons_1_3'
    elif lesson_number <= 6 and difficulty == 'Easy':
        key = 'lessons_4_6'
    elif lesson_number <= 8 and difficulty == 'Medium':
        key = 'lessons_4_8'
    elif lesson_number <= 10 and difficulty == 'Easy':
        key = 'lessons_7_10'
    elif lesson_number <= 15 and difficulty == 'Easy':
        key = 'lessons_11_15'
    elif difficulty == 'Medium':
        key = 'lessons_9_plus'
    elif difficulty == 'Hard' and lesson_number <= 3:
        key = 'lessons_1_3'
    elif difficulty == 'Hard':
        key = 'lessons_4_plus'
    else:
        key = 'lessons_16_plus' if difficulty == 'Easy' else list(progression.keys())[-1]
    
    return progression.get(key, progression[list(progression.keys())[0]])


def detect_lesson_type(concept):
    """
    Detect if lesson is theory-focused or code-focused
    Returns: 'theory' or 'code'
    
    Theory lessons: Rich conceptual explanations without mandatory code
    Code lessons: Practical examples with working code
    """
    concept_lower = concept.lower()
    
    # Theory-focused keywords (conceptual understanding)
    theory_keywords = [
        'introduction', 'intro to', 'overview', 'history', 'features', 
        'advantages', 'disadvantages', 'benefits', 'comparison', 'vs',
        'what is', 'why use', 'when to use', 'philosophy', 'principles',
        'concepts', 'fundamentals', 'basics of', 'getting started',
        'architecture', 'ecosystem', 'community', 'use cases',
        'applications', 'best practices', 'conventions', 'style guide'
    ]
    
    # Code-focused keywords (hands-on programming)
    code_keywords = [
        'variable', 'function', 'loop', 'conditional', 'if', 'else',
        'array', 'list', 'dictionary', 'object', 'class', 'method',
        'operator', 'expression', 'statement', 'syntax', 'data type',
        'string', 'number', 'boolean', 'null', 'undefined',
        'input', 'output', 'print', 'return', 'parameter', 'argument',
        'scope', 'closure', 'callback', 'promise', 'async', 'await',
        'exception', 'error handling', 'debugging', 'testing'
    ]
    
    # Check for theory keywords
    for keyword in theory_keywords:
        if keyword in concept_lower:
            return 'theory'
    
    # Check for code keywords
    for keyword in code_keywords:
        if keyword in concept_lower:
            return 'code'
    
    # Default: if lesson number 1-2, lean towards theory; otherwise code
    lesson_num = extract_lesson_number(concept)
    return 'theory' if lesson_num <= 2 else 'code'


def build_example_template(language, difficulty, lesson_number, concept):
    """
    Build specific example templates based on lesson progression
    """
    constraints = get_lesson_constraints(difficulty, lesson_number)
    example_type = constraints['example_type']
    
    templates = {
        'python': {
            'hello_world': 'Only use: print("Hello, World!") with simple string. NO variables, NO functions.',
            'variables_and_types': 'Use simple variable assignments (x = 5, name = "text") and print them. NO functions.',
            'simple_control_flow': 'Use simple if-else with basic conditions. Use simple for/while loops. NO functions yet.',
            'basic_functions': 'Now you can introduce simple functions with 1-2 parameters. Keep it very simple.',
            'function_basics': 'Show function definition, parameters, return values. Keep examples practical.',
            'intermediate_programming': 'Use functions, loops, data structures. Build on previous concepts.',
            'intermediate_advanced': 'Introduce classes, file operations, error handling.',
            'advanced_concepts': 'Show design patterns, OOP principles, architecture.',
            'expert_level': 'Advanced patterns, optimization, complex scenarios.'
        },
        'javascript': {
            'hello_world': 'Only use: console.log("Hello, World!") with simple string. NO variables, NO functions.',
            'variables_and_types': 'Use let/const with simple assignments and console.log. NO functions.',
            'simple_control_flow': 'Use simple if-else and basic for loops. NO functions yet.',
            'basic_functions': 'Now introduce simple arrow functions or function declarations.',
            'function_basics': 'Show function definition, parameters, return values, arrow functions.',
            'intermediate_programming': 'Use functions, arrays, objects, array methods.',
            'intermediate_advanced': 'Introduce classes, async/await, modules.',
            'advanced_concepts': 'Show design patterns, closures, prototypes.',
            'expert_level': 'Advanced patterns, performance optimization, complex apps.'
        },
        'java': {
            'hello_world': 'Only System.out.println("Hello, World!") inside main method. Keep it minimal.',
            'variables_and_types': 'Simple variable declarations and printing. Stay in main method.',
            'simple_control_flow': 'Use if-else and basic loops in main method. NO separate methods yet.',
            'basic_functions': 'Now introduce simple static methods.',
            'function_basics': 'Show method definition, parameters, return types.',
            'intermediate_programming': 'Use methods, arrays, ArrayList basics.',
            'intermediate_advanced': 'Introduce classes, objects, inheritance.',
            'advanced_concepts': 'Show design patterns, interfaces, abstract classes.',
            'expert_level': 'Advanced OOP, streams, concurrency, design patterns.'
        },
        'csharp': {
            'hello_world': 'Only Console.WriteLine("Hello, World!") in Main. Keep minimal.',
            'variables_and_types': 'Simple variable declarations and Console.WriteLine.',
            'simple_control_flow': 'Use if-else and basic loops in Main. NO separate methods.',
            'basic_functions': 'Introduce simple static methods.',
            'function_basics': 'Show method definition, parameters, return types.',
            'intermediate_programming': 'Use methods, arrays, List basics.',
            'intermediate_advanced': 'Introduce classes, properties, LINQ basics.',
            'advanced_concepts': 'Show design patterns, interfaces, generics.',
            'expert_level': 'Advanced C# features, async/await, design patterns.'
        }
    }
    
    return templates.get(language, templates['python']).get(example_type, '')


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


def auto_wrap_java_code(code):
    """
    Auto-wrap Java code in a proper class structure if missing.
    This allows simple code snippets like System.out.println() to work.
    """
    # Check if code already has a public class
    if re.search(r'public\s+class\s+\w+', code):
        return code
    
    # Check if code has any class definition
    if re.search(r'class\s+\w+', code):
        # Has a class but not public - make it public Main
        code = re.sub(r'class\s+(\w+)', 'public class Main', code, count=1)
        return code
    
    # Check if it has a main method but no class
    if re.search(r'public\s+static\s+void\s+main', code):
        return f"public class Main {{\n{code}\n}}"
    
    # It's just code statements - wrap it in full structure
    # Remove any Python-style print statements
    code = re.sub(r'\bprint\s*\(([^)]*)\)', r'System.out.println(\1)', code)
    
    # Clean up the code - remove any non-Java syntax
    lines = code.strip().split('\n')
    cleaned_lines = []
    for line in lines:
        # Skip Python-style comments at beginning, keep Java comments
        if line.strip().startswith('#') and not line.strip().startswith('//'):
            line = line.replace('#', '//', 1)
        cleaned_lines.append(line)
    
    cleaned_code = '\n        '.join(cleaned_lines)
    
    wrapped = f"""public class Main {{
    public static void main(String[] args) {{
        {cleaned_code}
    }}
}}"""
    return wrapped


def execute_java_code(code_to_run):
    """Execute Java code (basic implementation)"""
    try:
        # Auto-wrap code if it doesn't have proper class structure
        code_to_run = auto_wrap_java_code(code_to_run)
        
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


def auto_wrap_csharp_code(code):
    """
    Auto-wrap C# code in a proper class structure if missing.
    This allows simple code snippets like Console.WriteLine() to work.
    """
    # Check if code already has a class definition
    if re.search(r'class\s+\w+', code):
        # Ensure it has 'using System;' at the top
        if 'using System;' not in code:
            code = 'using System;\n\n' + code
        return code
    
    # Check if it has a Main method but no class
    if re.search(r'static\s+void\s+Main', code):
        code = f"using System;\n\nclass Program {{\n{code}\n}}"
        return code
    
    # It's just code statements - wrap it in full structure
    # Convert Python-style print to C# Console.WriteLine
    code = re.sub(r'\bprint\s*\(([^)]*)\)', r'Console.WriteLine(\1)', code)
    
    # Clean up the code - convert Python comments to C# comments
    lines = code.strip().split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('#') and not line.strip().startswith('//'):
            line = line.replace('#', '//', 1)
        cleaned_lines.append(line)
    
    cleaned_code = '\n        '.join(cleaned_lines)
    
    wrapped = f"""using System;

class Program {{
    static void Main() {{
        {cleaned_code}
    }}
}}"""
    return wrapped


def execute_csharp_code(code_to_run):
    """Execute C# code using dotnet"""
    try:
        # Auto-wrap code if it doesn't have proper class structure
        code_to_run = auto_wrap_csharp_code(code_to_run)
        
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


def get_language_structure_requirement(language, framework=None, is_selenium=False):
    """
    Returns mandatory code structure requirements for each language.
    This ensures AI generates properly structured code that can be executed.
    Includes support for Selenium sub-languages and various testing frameworks.
    """
    language_lower = language.lower() if language else 'python'
    
    # Base structures for regular programming
    structures = {
        'java': """
        ⚠️ JAVA CODE STRUCTURE IS MANDATORY:
        Java code MUST include the complete class structure to be executable.
        Always wrap your code like this:
        
        public class Main {
            public static void main(String[] args) {
                // Your code goes here
                System.out.println("Hello, World!");
            }
        }
        
        RULES:
        - Class name MUST be 'Main' (with capital M)
        - MUST have 'public class Main'
        - MUST have 'public static void main(String[] args)'
        - Use System.out.println() for output
        - DO NOT use 'print()' - that's Python syntax!
        """,
        
        'csharp': """
        ⚠️ C# CODE STRUCTURE IS MANDATORY:
        C# code MUST include the complete class structure to be executable.
        Always wrap your code like this:
        
        using System;
        
        class Program {
            static void Main() {
                // Your code goes here
                Console.WriteLine("Hello, World!");
            }
        }
        
        RULES:
        - Include 'using System;' at the top
        - Class name should be 'Program'
        - MUST have 'static void Main()'
        - Use Console.WriteLine() for output
        - DO NOT use 'print()' - that's Python syntax!
        """,
        
        'python': """
        ✅ PYTHON CODE:
        Python code can be written directly without class wrapping.
        Use print() for output.
        Example: print("Hello, World!")
        """,
        
        'javascript': """
        ✅ JAVASCRIPT CODE:
        JavaScript code can be written directly without class wrapping.
        Use console.log() for output.
        Example: console.log("Hello, World!");
        """
    }
    
    # Selenium-specific structures for different sub-languages and frameworks
    selenium_structures = {
        'python': {
            'default': """
            ✅ PYTHON SELENIUM CODE:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            
            driver = webdriver.Chrome()
            driver.get('https://example.com')
            print('Page title:', driver.title)
            driver.quit()
            
            RULES:
            - Import webdriver and By from selenium
            - Always quit() the driver at the end
            - Use print() for output
            """,
            'pytest': """
            ✅ PYTHON SELENIUM WITH PYTEST:
            import pytest
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            
            class TestExample:
                def setup_method(self):
                    self.driver = webdriver.Chrome()
                
                def test_page_title(self):
                    self.driver.get('https://example.com')
                    assert 'Example' in self.driver.title
                
                def teardown_method(self):
                    self.driver.quit()
            
            RULES:
            - Use pytest fixtures or setup_method/teardown_method
            - Test functions must start with 'test_'
            - Use assert statements for validations
            - Class names should start with 'Test'
            """,
            'unittest': """
            ✅ PYTHON SELENIUM WITH UNITTEST:
            import unittest
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            
            class TestExample(unittest.TestCase):
                def setUp(self):
                    self.driver = webdriver.Chrome()
                
                def test_page_title(self):
                    self.driver.get('https://example.com')
                    self.assertIn('Example', self.driver.title)
                
                def tearDown(self):
                    self.driver.quit()
            
            if __name__ == '__main__':
                unittest.main()
            
            RULES:
            - Class must inherit from unittest.TestCase
            - Use setUp() and tearDown() for lifecycle
            - Use self.assertEqual, self.assertIn, etc. for assertions
            - Test methods must start with 'test_'
            """,
            'Robot Framework': """
            ✅ ROBOT FRAMEWORK SELENIUM CODE:
            *** Settings ***
            Library    SeleniumLibrary
            
            *** Test Cases ***
            Example Test
                Open Browser    https://example.com    chrome
                Title Should Contain    Example
                Close Browser
            
            RULES:
            - Use *** Settings *** to import SeleniumLibrary
            - Use *** Test Cases *** for test definitions
            - Keywords are space-separated
            - Use 4 spaces for argument separation
            """
        },
        'java': {
            'default': """
            ⚠️ JAVA SELENIUM CODE STRUCTURE IS MANDATORY:
            import org.openqa.selenium.WebDriver;
            import org.openqa.selenium.chrome.ChromeDriver;
            
            public class Main {
                public static void main(String[] args) {
                    WebDriver driver = new ChromeDriver();
                    driver.get("https://example.com");
                    System.out.println("Title: " + driver.getTitle());
                    driver.quit();
                }
            }
            
            RULES:
            - MUST have 'public class Main' or test class name
            - Import WebDriver and browser driver classes
            - Always call driver.quit() at the end
            """,
            'TestNG': """
            ⚠️ JAVA SELENIUM WITH TESTNG - CLASS STRUCTURE MANDATORY:
            import org.openqa.selenium.WebDriver;
            import org.openqa.selenium.chrome.ChromeDriver;
            import org.testng.Assert;
            import org.testng.annotations.*;
            
            public class ExampleTest {
                private WebDriver driver;
                
                @BeforeMethod
                public void setUp() {
                    driver = new ChromeDriver();
                }
                
                @Test
                public void testPageTitle() {
                    driver.get("https://example.com");
                    Assert.assertTrue(driver.getTitle().contains("Example"));
                }
                
                @AfterMethod
                public void tearDown() {
                    driver.quit();
                }
            }
            
            RULES:
            - MUST have public class with a name (e.g., ExampleTest)
            - Use @BeforeMethod, @AfterMethod for setup/teardown
            - Use @Test annotation for test methods
            - Use Assert.assertEquals, Assert.assertTrue for validations
            """,
            'JUnit': """
            ⚠️ JAVA SELENIUM WITH JUNIT - CLASS STRUCTURE MANDATORY:
            import org.openqa.selenium.WebDriver;
            import org.openqa.selenium.chrome.ChromeDriver;
            import org.junit.jupiter.api.*;
            import static org.junit.jupiter.api.Assertions.*;
            
            public class ExampleTest {
                private WebDriver driver;
                
                @BeforeEach
                void setUp() {
                    driver = new ChromeDriver();
                }
                
                @Test
                void testPageTitle() {
                    driver.get("https://example.com");
                    assertTrue(driver.getTitle().contains("Example"));
                }
                
                @AfterEach
                void tearDown() {
                    driver.quit();
                }
            }
            
            RULES:
            - MUST have public class with a name
            - Use @BeforeEach, @AfterEach for lifecycle (JUnit 5)
            - Use @Test annotation for test methods
            - Use Assertions.assertEquals, assertTrue, etc.
            """,
            'Cucumber': """
            ⚠️ JAVA CUCUMBER/BDD - CLASS STRUCTURE MANDATORY:
            // Step Definitions file
            import io.cucumber.java.en.*;
            import org.openqa.selenium.WebDriver;
            import org.openqa.selenium.chrome.ChromeDriver;
            import static org.junit.Assert.*;
            
            public class StepDefinitions {
                private WebDriver driver;
                
                @Given("I open the browser")
                public void openBrowser() {
                    driver = new ChromeDriver();
                }
                
                @When("I navigate to {string}")
                public void navigateTo(String url) {
                    driver.get(url);
                }
                
                @Then("the title should contain {string}")
                public void verifyTitle(String expected) {
                    assertTrue(driver.getTitle().contains(expected));
                    driver.quit();
                }
            }
            
            RULES:
            - MUST have public class for step definitions
            - Use @Given, @When, @Then annotations
            - Pair with .feature files for Gherkin scenarios
            """
        },
        'javascript': {
            'default': """
            ✅ JAVASCRIPT SELENIUM CODE:
            const { Builder, By, until } = require('selenium-webdriver');
            
            async function run() {
                let driver = await new Builder().forBrowser('chrome').build();
                try {
                    await driver.get('https://example.com');
                    console.log('Title:', await driver.getTitle());
                } finally {
                    await driver.quit();
                }
            }
            run();
            
            RULES:
            - Use async/await for Selenium operations
            - Wrap in try/finally to ensure driver.quit()
            - Use console.log() for output
            """,
            'Mocha': """
            ✅ JAVASCRIPT SELENIUM WITH MOCHA:
            const { Builder, By, until } = require('selenium-webdriver');
            const assert = require('assert');
            
            describe('Example Test', function() {
                let driver;
                this.timeout(30000);
                
                beforeEach(async function() {
                    driver = await new Builder().forBrowser('chrome').build();
                });
                
                it('should have correct title', async function() {
                    await driver.get('https://example.com');
                    const title = await driver.getTitle();
                    assert(title.includes('Example'));
                });
                
                afterEach(async function() {
                    await driver.quit();
                });
            });
            
            RULES:
            - Use describe() and it() blocks
            - Use beforeEach/afterEach for setup/teardown
            - Set appropriate timeout for Selenium operations
            - Use async/await throughout
            """,
            'Jest': """
            ✅ JAVASCRIPT SELENIUM WITH JEST:
            const { Builder, By, until } = require('selenium-webdriver');
            
            describe('Example Test', () => {
                let driver;
                
                beforeEach(async () => {
                    driver = await new Builder().forBrowser('chrome').build();
                }, 30000);
                
                afterEach(async () => {
                    await driver.quit();
                });
                
                test('should have correct title', async () => {
                    await driver.get('https://example.com');
                    const title = await driver.getTitle();
                    expect(title).toContain('Example');
                }, 30000);
            });
            
            RULES:
            - Use describe() and test() blocks
            - Use Jest matchers like expect().toContain()
            - Set timeout as second parameter to test/beforeEach
            - Use async/await throughout
            """
        },
        'csharp': {
            'default': """
            ⚠️ C# SELENIUM CODE STRUCTURE IS MANDATORY:
            using OpenQA.Selenium;
            using OpenQA.Selenium.Chrome;
            using System;
            
            class Program {
                static void Main() {
                    IWebDriver driver = new ChromeDriver();
                    driver.Navigate().GoToUrl("https://example.com");
                    Console.WriteLine("Title: " + driver.Title);
                    driver.Quit();
                }
            }
            
            RULES:
            - MUST have class Program with static void Main()
            - Use IWebDriver interface
            - Use driver.Navigate().GoToUrl() for navigation
            - Always call driver.Quit() at the end
            """,
            'NUnit': """
            ⚠️ C# SELENIUM WITH NUNIT - CLASS STRUCTURE MANDATORY:
            using OpenQA.Selenium;
            using OpenQA.Selenium.Chrome;
            using NUnit.Framework;
            
            [TestFixture]
            public class ExampleTest {
                private IWebDriver driver;
                
                [SetUp]
                public void SetUp() {
                    driver = new ChromeDriver();
                }
                
                [Test]
                public void TestPageTitle() {
                    driver.Navigate().GoToUrl("https://example.com");
                    Assert.That(driver.Title.Contains("Example"));
                }
                
                [TearDown]
                public void TearDown() {
                    driver.Quit();
                }
            }
            
            RULES:
            - MUST have [TestFixture] attribute on class
            - Use [SetUp], [TearDown] for lifecycle
            - Use [Test] attribute for test methods
            - Use Assert.That, Assert.AreEqual for validations
            """,
            'MSTest': """
            ⚠️ C# SELENIUM WITH MSTEST - CLASS STRUCTURE MANDATORY:
            using OpenQA.Selenium;
            using OpenQA.Selenium.Chrome;
            using Microsoft.VisualStudio.TestTools.UnitTesting;
            
            [TestClass]
            public class ExampleTest {
                private IWebDriver driver;
                
                [TestInitialize]
                public void SetUp() {
                    driver = new ChromeDriver();
                }
                
                [TestMethod]
                public void TestPageTitle() {
                    driver.Navigate().GoToUrl("https://example.com");
                    Assert.IsTrue(driver.Title.Contains("Example"));
                }
                
                [TestCleanup]
                public void TearDown() {
                    driver.Quit();
                }
            }
            
            RULES:
            - MUST have [TestClass] attribute on class
            - Use [TestInitialize], [TestCleanup] for lifecycle
            - Use [TestMethod] attribute for test methods
            - Use Assert.IsTrue, Assert.AreEqual for validations
            """,
            'SpecFlow': """
            ⚠️ C# SELENIUM WITH SPECFLOW/BDD - CLASS STRUCTURE MANDATORY:
            using OpenQA.Selenium;
            using OpenQA.Selenium.Chrome;
            using TechTalk.SpecFlow;
            using NUnit.Framework;
            
            [Binding]
            public class StepDefinitions {
                private IWebDriver driver;
                
                [Given(@"I open the browser")]
                public void OpenBrowser() {
                    driver = new ChromeDriver();
                }
                
                [When(@"I navigate to (.*)")]
                public void NavigateTo(string url) {
                    driver.Navigate().GoToUrl(url);
                }
                
                [Then(@"the title should contain (.*)")]
                public void VerifyTitle(string expected) {
                    Assert.That(driver.Title.Contains(expected));
                    driver.Quit();
                }
            }
            
            RULES:
            - MUST have [Binding] attribute on class
            - Use [Given], [When], [Then] for step definitions
            - Pair with .feature files for Gherkin scenarios
            """
        }
    }
    
    # If this is a Selenium request, return Selenium-specific structure
    if is_selenium:
        lang_selenium = selenium_structures.get(language_lower, selenium_structures.get('python'))
        if framework:
            framework_key = framework.replace(' ', '_') if framework else 'default'
            return lang_selenium.get(framework, lang_selenium.get('default', ''))
        return lang_selenium.get('default', '')
    
    # Return base language structure
    return structures.get(language_lower, structures.get('python', ''))


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
    
    # *** PROGRESSIVE LEARNING: Extract difficulty, skill level, and lesson number ***
    difficulty = data.get('difficulty', 'Medium')
    skill_level = data.get('skillLevel', 'Intermediate')
    lesson_number = extract_lesson_number(concept)  # NEW: Extract lesson position
    lesson_type = detect_lesson_type(concept)  # NEW: Detect if theory or code-focused
    
    if not concept:
        return jsonify({"error": "Concept not provided"}), 400
    
    # *** PROGRESSIVE LEARNING: Get appropriate constraints for this lesson ***
    lesson_constraints = get_lesson_constraints(difficulty, lesson_number)
    example_template = build_example_template(
        language if not (is_selenium and sub_language) else sub_language,
        difficulty,
        lesson_number,
        concept
    )
    
    # Adjust max_tokens based on lesson type
    # Theory lessons need more tokens for comprehensive explanations
    # Code lessons need moderate tokens for explanation + code
    max_tokens_for_lesson = 3072 if lesson_type == 'theory' else 1536

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

    # *** PROGRESSIVE LEARNING: Use lesson-specific constraints ***
    
    # Build different prompts for theory vs code lessons
    if lesson_type == 'theory':
        # Theory-focused prompt: Emphasize comprehensive explanation, code is optional
        system_prompt = f"""You are an expert, friendly, and patient {language_context} instructor.
        
        ═══════════════════════════════════════════════════════════════════
        📚 LESSON TYPE: THEORY / CONCEPTUAL
        ═══════════════════════════════════════════════════════════════════
        This is a THEORY-FOCUSED lesson about: {concept}
        
        Your goal: Provide a COMPREHENSIVE, DETAILED explanation of the concept.
        Code examples are OPTIONAL - only include if they genuinely enhance understanding.
        
        ═══════════════════════════════════════════════════════════════════
        📋 LESSON CONTEXT
        ═══════════════════════════════════════════════════════════════════
        Difficulty: {difficulty}
        Skill Level: {skill_level}
        Lesson Number: {lesson_number}
        Language: {language_context}
        Domain: {domain.replace('-', ' ').title()}
        {f"Framework: {framework}" if framework else ""}
        
        ═══════════════════════════════════════════════════════════════════
        ✅ WHAT TO INCLUDE (Theory Lesson)
        ═══════════════════════════════════════════════════════════════════
        
        1. **Clear Definition**: What is {concept}?
        2. **Why It Matters**: Importance and benefits
        3. **Key Characteristics**: Main features and properties
        4. **Real-World Applications**: Where/when it's used
        5. **Comparison** (if relevant): How it compares to alternatives
        6. **Best Practices**: Important guidelines
        7. **Common Use Cases**: Practical scenarios
        
        **Code Example**: OPTIONAL - Only include if it truly helps illustrate the concept.
        For purely conceptual topics like "History", "Introduction", "Overview", "Importance", etc.,
        DO NOT include any code - just return an empty string "" for code_example.
        If no code is needed, set "code_example" to an empty string "".
        
        ═══════════════════════════════════════════════════════════════════
        � RESPONSE FORMAT (STRICT JSON)
        ═══════════════════════════════════════════════════════════════════
        
        {{
            "lesson_type": "theory",
            "explanation": "A comprehensive, detailed explanation covering all key aspects of {concept}. Use markdown formatting: **bold** for emphasis, bullet points for lists, numbered lists for steps. Make this rich and informative (300-600 words).",
            "code_example": ""
        }}
        
        ⚠️ IMPORTANT: For theory lessons like history, overview, introduction, etc., 
        always set code_example to empty string "". Do not force code where it's not needed!
        
        ⚠️ CRITICAL: Make the explanation RICH and COMPREHENSIVE. This is theory, so focus on deep understanding!
        """
    else:
        # Code-focused prompt: Balanced explanation with mandatory practical example
        system_prompt = f"""You are an expert, friendly, and patient {language_context} instructor.
        
        ═══════════════════════════════════════════════════════════════════
        💻 LESSON TYPE: CODE / PRACTICAL
        ═══════════════════════════════════════════════════════════════════
        This is a CODE-FOCUSED lesson about: {concept}
        
        Your goal: Provide a clear explanation WITH a practical, working code example.
        
        ═══════════════════════════════════════════════════════════════════
        📋 LESSON CONTEXT
        ═══════════════════════════════════════════════════════════════════
        Difficulty: {difficulty}
        Skill Level: {skill_level}
        Lesson Number: {lesson_number}
        Language: {language_context}
        Domain: {domain.replace('-', ' ').title()}
        {f"Framework: {framework} - {framework_focus}" if framework and framework_focus else ""}
        
        ═══════════════════════════════════════════════════════════════════
        🎯 STRICT LESSON-SPECIFIC REQUIREMENTS (Lesson {lesson_number})
        ═══════════════════════════════════════════════════════════════════
        
        ALLOWED CONCEPTS FOR THIS LESSON:
        {', '.join(lesson_constraints['allowed_concepts'])}
        
        CONCEPTS TO STRICTLY AVOID:
        {', '.join(lesson_constraints['avoid'])}
        
        MAXIMUM CODE LENGTH: {lesson_constraints['max_lines']} lines
        
        EXAMPLE TEMPLATE GUIDANCE:
        {example_template}
        
        ═══════════════════════════════════════════════════════════════════
        ⚠️ CRITICAL RULES - MUST FOLLOW
        ═══════════════════════════════════════════════════════════════════
        
        1. This is LESSON {lesson_number} - The learner has NOT learned concepts from future lessons yet!
        2. DO NOT use any concepts from the "AVOID" list above
        3. ONLY use concepts from the "ALLOWED" list above
        4. Keep code under {lesson_constraints['max_lines']} lines
        5. Build ONLY on concepts from lessons 1 through {lesson_number}
        6. Make the example IMMEDIATELY runnable and understandable
        
        For Lesson 1 (Introduction): Use ONLY print/console.log with simple strings. NO variables!
        For Lessons 2-3: Can add simple variables if allowed
        For Lessons 4-6: Can add conditionals/loops if allowed
        For Lessons 7+: Can gradually introduce more concepts if allowed
        
        ═══════════════════════════════════════════════════════════════════
        {f'''🔧 FRAMEWORK-SPECIFIC REQUIREMENTS ({framework})
        ═══════════════════════════════════════════════════════════════════
        Test Structure: {test_structure}
        Imports: {import_statement}
        Patterns: {framework_patterns}
        Setup/Teardown: {framework_setup}
        Assertions: {assertion_style}
        Lifecycle: {lifecycle_methods}
        Focus: {framework_focus}
        ═══════════════════════════════════════════════════════════════════
        ''' if framework and framework_info else ''}
        
        ═══════════════════════════════════════════════════════════════════
        📋 RESPONSE FORMAT (STRICT JSON)
        ═══════════════════════════════════════════════════════════════════
        
        You MUST respond with a JSON object. Do NOT include any conversational filler, greetings, or additional text outside the JSON.
        The JSON structure must be:
        {{
            "lesson_type": "code",
            "explanation": "A clear explanation of {concept} appropriate for Lesson {lesson_number} at {difficulty} level (150-300 words).",
            "code_example": "Working code example using ONLY the allowed concepts listed above. Maximum {lesson_constraints['max_lines']} lines. REQUIRED for code lessons."
        }}
        
        ═══════════════════════════════════════════════════════════════════
        🎨 CODE EXAMPLE REQUIREMENTS
        ═══════════════════════════════════════════════════════════════════
        - Language: {example_language}
        - Follow the EXAMPLE TEMPLATE GUIDANCE exactly
        - Use ONLY concepts from the ALLOWED list
        - Maximum {lesson_constraints['max_lines']} lines of code
        - Include helpful comments for beginners
        {f"- Use {framework} framework patterns: {framework_patterns}" if framework else ""}
        {f"- Required imports: {import_statement}" if import_statement else ""}
        {f"- Use {assertion_style} for validations" if assertion_style and framework else ""}
        {f"- Include {lifecycle_methods}" if lifecycle_methods and framework else ""}
        
        ═══════════════════════════════════════════════════════════════════
        🏗️ MANDATORY LANGUAGE-SPECIFIC CODE STRUCTURE
        ═══════════════════════════════════════════════════════════════════
        {get_language_structure_requirement(example_language, framework, is_selenium)}
        
        ═══════════════════════════════════════════════════════════════════
        ✅ VALIDATION CHECKLIST (Must pass ALL)
        ═══════════════════════════════════════════════════════════════════
        [ ] Code uses ONLY allowed concepts
        [ ] Code avoids ALL forbidden concepts
        [ ] Code length ≤ {lesson_constraints['max_lines']} lines
        [ ] Example is appropriate for Lesson {lesson_number}
        [ ] JSON is perfectly valid (no triple quotes inside strings)
        [ ] Code is immediately runnable by a beginner
        
        **CRITICAL:** Escape internal quotes properly (use \\" for quotes inside JSON strings).
        """
    
    # Create the messages list using the appropriate system prompt
    prompt_messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user", 
            "content": f"Generate Lesson {lesson_number} ({'THEORY' if lesson_type == 'theory' else 'CODE'}) content: \"{concept}\" for {difficulty} level ({skill_level} skill) in {language_context}{f' using {framework}' if framework else ''}."
        }
    ]

    try:
        ai_output = call_llm(prompt_messages, DEFAULT_LLM_PROVIDER, response_format_type="json_object", max_tokens=max_tokens_for_lesson)
        
        # Parse the AI response JSON and return as proper Flask response
        try:
            import json
            parsed_response = json.loads(ai_output)
            
            # Ensure lesson_type is included in response
            if 'lesson_type' not in parsed_response:
                parsed_response['lesson_type'] = lesson_type
            
            # For theory lessons, ensure code_example exists (can be empty string)
            if lesson_type == 'theory' and 'code_example' not in parsed_response:
                parsed_response['code_example'] = ""
            
            # DEBUG: Log what we're sending to frontend
            logger.info(f"📚 Lesson Generated - Type: {lesson_type}, Concept: {concept}")
            logger.info(f"📊 Response keys: {list(parsed_response.keys())}")
            logger.info(f"📝 Explanation length: {len(parsed_response.get('explanation', ''))} chars")
            logger.info(f"💻 Code example length: {len(parsed_response.get('code_example', ''))} chars")
            
            return jsonify(parsed_response), 200
        except json.JSONDecodeError as json_err:
            print(f"Error parsing AI response JSON: {json_err}")
            print(f"Raw AI response: {ai_output}")
            # Fallback response if AI doesn't return valid JSON
            fallback_response = {
                "lesson_type": lesson_type,
                "explanation": f"This lesson covers: {concept}",
                "code_example": f"# {concept} example\n# Your code here" if lesson_type == 'code' else ""
            }
            return jsonify(fallback_response), 200
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


# --- API-compatible Routes (for frontend compatibility) ---
@app.route('/api/ai/syllabus', methods=['POST'])
def api_generate_syllabus():
    """API-compatible route for syllabus generation"""
    return generate_syllabus()


@app.route('/api/ai/lesson', methods=['POST'])
def api_generate_lesson():
    """API-compatible route for lesson generation"""
    return generate_lesson()


@app.route('/api/ai/chat', methods=['POST'])
def api_chat_with_ai():
    """API-compatible route for AI chat"""
    return chat_with_ai()


@app.route('/api/ai/run', methods=['POST'])
def api_run_code():
    """API-compatible route for code execution"""
    return run_code()


@app.route('/api/ai/explain', methods=['POST'])
def api_explain_code():
    """API-compatible route for code explanation"""
    return explain_code()


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """API-compatible route for user registration"""
    return register()


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """API-compatible route for user login"""
    return login()


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
