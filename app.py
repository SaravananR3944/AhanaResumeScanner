from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF for PDF text extraction
import re
import os
import phonenumbers # type: ignore

# Initialize Flask App
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend communication

# Directory to store uploaded files
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Allowed file types
ALLOWED_EXTENSIONS = {"pdf"}

def allowed_file(filename):
    """Check if the file has an allowed extension (PDF only)."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF."""
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text("text") for page in doc)
    return text


def extract_contact_details(text, filename):
    """
    Extract Name (from filename), Email, and Phone Number from resume text.
    
    Args:
        text (str): The resume text content
        filename (str): The uploaded file's name
        
    Returns:
        dict: Dictionary containing extracted Name, Email, and Phone
    """
    result = {
        "Name": "Not Found",
        "Email": "Not Found",
        "Phone": "Not Found"
    }
    
    # Extract name from filename
    base_name = os.path.splitext(filename)[0]
    
    # List of words to omit
    words_to_omit = ["resume", "updated", "update", "profile", "cv", "latest", "final", "new", "pdf", "uploaded"]
    
    # Replace underscores with spaces
    name = base_name.replace("_", " ").replace("-", " ")
    
    # Remove integers and words to omit
    for word in words_to_omit:
        name = re.sub(r'\b' + word + r'\b', '', name, flags=re.IGNORECASE)
    
    # Remove any standalone digits
    name = re.sub(r'\b\d+\b', '', name)
    
    # Remove specific symbols: -, (, )
    name = re.sub(r'[-()]', '', name)
    
    # Clean up extra spaces and title case the result
    name = re.sub(r'\s+', ' ', name).strip().title()
    
    if name:
        result["Name"] = name
    
    # Clean the text
    text = text.replace('\r', '\n')
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Extract email
    text = re.sub(r'(?<!\s)(www\.)', r' \1', text)
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    email_matches = re.findall(email_pattern, text)
    if email_matches:
        result["Email"] = email_matches[0]
    
    # Extract phone number
    phone_patterns = [
        r'(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'(?:\+\d{1,3}[-.\s]?)?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        r'(?:\+\d{1,3}[-.\s]?)?\d{10,}',
    ]
    for pattern in phone_patterns:
        phone_matches = re.findall(pattern, text)
        if phone_matches:
            result["Phone"] = phone_matches[0]
            break
    
    # Validate phone number with phonenumbers
    if result["Phone"] == "Not Found":
        try:
            for match in phonenumbers.PhoneNumberMatcher(text, None):
                result["Phone"] = phonenumbers.format_number(
                    match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                )
                break
        except:
            pass
    
    return result

def extract_section(text, section_headers):
    """Extract a specific section from the resume using more robust detection.
    Returns the section text and the end index of the section."""
    lines = text.split("\n")
    start_idx = -1
    end_idx = len(lines)
    
    # Improved section header detection - match exact headers with word boundaries
    for i, line in enumerate(lines):
        # Check if the line contains any of the section headers as a standalone word
        if any(re.search(rf'\b{re.escape(header)}\b', line, re.IGNORECASE) for header in section_headers):
            start_idx = i
            break
    
    if start_idx == -1:
        return "", end_idx
    
    # Common section headers in resumes
    next_section_headers = ["Education", "Experience", "Work Experience", "Employment", 
                           "Skills", "Technical Skills", "Projects", "Certifications", 
                           "Awards", "Publications", "Languages", "Interests", "References"]
    
    # Remove headers we're currently looking for to avoid false endings
    for header in section_headers:
        for next_header in list(next_section_headers):
            if header.lower() == next_header.lower():
                next_section_headers.remove(next_header)
    
    for i in range(start_idx + 1, len(lines)):
        # Look for the next section header to determine where current section ends
        if any(re.search(rf'\b{re.escape(header)}\b', lines[i], re.IGNORECASE) for header in next_section_headers):
            end_idx = i
            break
    
    return "\n".join(lines[start_idx+1:end_idx]), end_idx

def extract_education(text):
    """Extract Education Details with improved matching."""
    # Extract the education section first
    education_section, _ = extract_section(text, ["Education", "Academic Background", "Qualification", "Educational Background"])
    
    if not education_section:
        return []
    
    # Education specific keywords and patterns
    education_keywords = [
        "B.E", "B.Tech", "M.Tech", "Bachelor", "Master", "Ph.D", "Degree", 
        "University", "Institute", "College", "School", "GPA", "CGPA",
        "Engineering", "Sciences", "Arts", "Commerce", "Diploma"
    ]
    
    # Pattern for dates: 2010-2014, 2010 - 2014, 2010—Present, etc.
    date_pattern = r"(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current|ongoing)"
    
    education_entries = []
    current_entry = []
    
    # Process the education section line by line
    for line in education_section.split("\n"):
        line = line.strip()
        if not line:
            if current_entry:
                education_entries.append(" ".join(current_entry))
                current_entry = []
            continue
        
        # Start of a new education entry if it has date or contains education keywords
        if (re.search(date_pattern, line, re.IGNORECASE) or 
            any(re.search(rf'\b{re.escape(keyword)}\b', line, re.IGNORECASE) for keyword in education_keywords)):
            if current_entry:  # Save previous entry if exists
                education_entries.append(" ".join(current_entry))
                current_entry = []
            current_entry.append(line)
        else:
            # Continue with the current entry
            current_entry.append(line)
    
    # Add the last entry if it exists
    if current_entry:
        education_entries.append(" ".join(current_entry))
    
    # If no structured entries were found, fall back to line-by-line with keyword matching
    if not education_entries:
        education_entries = [
            line.strip() for line in education_section.split("\n") 
            if line.strip() and (
                any(re.search(rf'\b{re.escape(keyword)}\b', line, re.IGNORECASE) for keyword in education_keywords) or
                re.search(date_pattern, line, re.IGNORECASE)
            )
        ]
    
    return education_entries


def extract_experience(text):
    """
    Extract work experience details from a resume.
    Returns an array of experience entries or an empty array if no experience is found.
    """
    # First check if an experience section exists
    experience_section = extract_experience_section(text)
    
    if not experience_section:
        return []  # No experience section found
    
    # Extract individual experience entries
    experiences = parse_experience_entries(experience_section)
    
    # If no structured entries were found, return empty list indicating no experience
    if not experiences:
        return []
    
    return experiences

def extract_experience_section(text):
    """
    Extract only the experience section from the resume text.
    Uses section headers and next section detection to isolate experience content.
    """
    # Common section headers in resumes
    experience_headers = [
        r"(?:^|\n)\s*WORK EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*EMPLOYMENT HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*PROFESSIONAL EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*WORK HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*RELEVANT EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*CAREER HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*EMPLOYMENT\s*(?:$|\n)",
        r"(?:^|\n)\s*PROFESSIONAL BACKGROUND\s*(?:$|\n)"
    ]
    
    # Common next section headers in resumes
    next_section_headers = [
        r"(?:^|\n)\s*EDUCATION\s*(?:$|\n)",
        r"(?:^|\n)\s*SKILLS\s*(?:$|\n)",
        r"(?:^|\n)\s*CERTIFICATIONS\s*(?:$|\n)",
        r"(?:^|\n)\s*AWARDS\s*(?:$|\n)",
        r"(?:^|\n)\s*PROJECTS\s*(?:$|\n)",
        r"(?:^|\n)\s*ACHIEVEMENTS\s*(?:$|\n)",
        r"(?:^|\n)\s*PUBLICATIONS\s*(?:$|\n)",
        r"(?:^|\n)\s*REFERENCES\s*(?:$|\n)",
        r"(?:^|\n)\s*LANGUAGES\s*(?:$|\n)",
        r"(?:^|\n)\s*INTERESTS\s*(?:$|\n)",
        r"(?:^|\n)\s*VOLUNTEER\s*(?:$|\n)",
        r"(?:^|\n)\s*ADDITIONAL INFORMATION\s*(?:$|\n)",
        r"(?:^|\n)\s*PERSONAL PROJECTS\s*(?:$|\n)",
        r"(?:^|\n)\s*EXTRACURRICULAR\s*(?:$|\n)"
    ]
    
    # Normalize line breaks and whitespace
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n+', '\n', text)
    text = text.strip()
    
    # Look for experience section header
    start_idx = -1
    experience_header_match = None
    
    for pattern in experience_headers:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start_idx = match.end()
            experience_header_match = match.group(0).strip()
            break
    
    if start_idx == -1:
        return ""  # No experience section found
    
    # Find the end of the experience section (start of next section)
    end_idx = len(text)
    
    for pattern in next_section_headers:
        match = re.search(pattern, text[start_idx:], re.IGNORECASE)
        if match:
            end_idx = start_idx + match.start()
            break
    
    # Extract the experience section
    experience_section = text[start_idx:end_idx].strip()
    
    # Additional filtering to avoid capturing contact info
    # Check if the section contains email, phone, or LinkedIn patterns
    contact_patterns = [
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Email
        r'(?:\+\d{1,3}[-\.\s]?)?\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}',  # Phone
        r'\d{10}',  # 10-digit phone without formatting
        r'linkedin\.com\/in\/[a-zA-Z0-9_-]+',  # LinkedIn URL
        r'[a-zA-Z]+\s*\|\s*LinkedIn'  # Name | LinkedIn format
    ]
    
    # If the section is too short or contains mostly contact information, reject it
    if len(experience_section) < 20 or experience_section.count('\n') < 2:
        contact_matches = 0
        for pattern in contact_patterns:
            if re.search(pattern, experience_section, re.IGNORECASE):
                contact_matches += 1
        
        # If we found contact info in a small section, it's probably not experience
        if contact_matches > 0:
            return ""
    
    # Check if the section has experience-like content
    experience_indicators = [
        r'\b(20\d{2}|19\d{2})[\s,-]+(?:present|current|20\d{2}|19\d{2})\b',  # Date ranges
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,-]+\d{4}',  # Month Year
        r'\b(?:managed|led|developed|implemented|created|designed|responsible for|collaborated|worked with)\b',  # Job verbs
        r'\b(?:Manager|Engineer|Developer|Analyst|Consultant|Specialist|Director|Coordinator|Supervisor)\b'  # Job titles
    ]
    
    has_experience_content = False
    for pattern in experience_indicators:
        if re.search(pattern, experience_section, re.IGNORECASE):
            has_experience_content = True
            break
    
    if not has_experience_content:
        return ""
        
    return experience_section

def parse_experience_entries(experience_section):
    """
    Parse individual experience entries from the experience section.
    """
    if not experience_section:
        return []
    
    # Common patterns for experience entries
    date_pattern = r'(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|(?:19|20)\d{2})\s*[-–—]\s*(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|(?:19|20)\d{2}|Present|Current|Now)'
    job_title_pattern = r'\b(?:Senior|Junior|Lead|Chief|Principal|Associate|Assistant)?\s*(?:Software|Systems|Data|Project|Product|Marketing|Sales|HR|Human Resources|Financial|Finance|Web|UI\/UX|Frontend|Backend|Full[ -]Stack|DevOps|QA|Test)?\s*(?:Engineer|Developer|Analyst|Manager|Consultant|Coordinator|Specialist|Director|Designer|Architect|Intern|Administrator|Officer|Executive|Representative|Associate)\b'
    company_pattern = r'\b[A-Z][A-Za-z0-9\s,\.&\'-]+(?:Inc|LLC|Ltd|Corporation|Corp|Company|Co|Group|GmbH)?\b'
    
    # Try different approaches to split the experience section into entries
    
    # Approach 1: Split by blank lines
    entries = re.split(r'\n\s*\n', experience_section)
    
    # Approach 2: If approach 1 yields only one entry, try to split by date patterns
    if len(entries) <= 1:
        lines = experience_section.split('\n')
        current_entry = []
        all_entries = []
        
        for i, line in enumerate(lines):
            if re.search(date_pattern, line, re.IGNORECASE) and (i == 0 or not re.search(date_pattern, lines[i-1], re.IGNORECASE)):
                if current_entry:
                    all_entries.append('\n'.join(current_entry))
                current_entry = [line]
            else:
                current_entry.append(line)
        
        if current_entry:
            all_entries.append('\n'.join(current_entry))
        
        if len(all_entries) > 1:
            entries = all_entries
    
    # Approach 3: If approaches 1 and 2 fail, try to split by job titles or companies
    if len(entries) <= 1:
        lines = experience_section.split('\n')
        current_entry = []
        all_entries = []
        
        for i, line in enumerate(lines):
            if ((re.search(job_title_pattern, line, re.IGNORECASE) or 
                 re.search(company_pattern, line, re.IGNORECASE)) and 
                len(line) < 100 and i > 0):
                
                # Only start a new entry if this looks like a header rather than a sentence
                if not re.search(r'[.,:;]$', lines[i-1]) and not re.search(r'^[a-z]', line):
                    if current_entry:
                        all_entries.append('\n'.join(current_entry))
                    current_entry = [line]
                    continue
            
            current_entry.append(line)
        
        if current_entry:
            all_entries.append('\n'.join(current_entry))
        
        if len(all_entries) > 1:
            entries = all_entries
    
    # Filter entries to ensure they contain actual experience information
    valid_entries = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        
        # Check if entry contains date ranges, job verbs, or job titles
        has_date = re.search(date_pattern, entry, re.IGNORECASE)
        has_job_title = re.search(job_title_pattern, entry, re.IGNORECASE)
        has_job_verbs = re.search(r'\b(?:managed|led|developed|implemented|created|designed|responsible for|collaborated|worked with)\b', 
                                 entry, re.IGNORECASE)
        
        # Check it's not just contact information
        is_contact = re.search(r'(?:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|(?:\+\d{1,3}[-\.\s]?)?\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}|\d{10}|linkedin\.com)', 
                              entry, re.IGNORECASE)
        
        if (has_date or has_job_title or has_job_verbs) and not is_contact:
            valid_entries.append(entry)
    
    return valid_entries

def has_work_experience_section(text):
    """
    Check if the resume contains a work experience section.
    """
    experience_headers = [
        r"(?:^|\n)\s*WORK EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*EMPLOYMENT HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*PROFESSIONAL EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*WORK HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*RELEVANT EXPERIENCE\s*(?:$|\n)",
        r"(?:^|\n)\s*CAREER HISTORY\s*(?:$|\n)",
        r"(?:^|\n)\s*EMPLOYMENT\s*(?:$|\n)",
        r"(?:^|\n)\s*PROFESSIONAL BACKGROUND\s*(?:$|\n)"
    ]
    
    for pattern in experience_headers:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False

def process_resume(text):
    """
    Main function to process a resume and extract work experience.
    Returns a message if no experience is found.
    """
    # First check if the resume has a work experience section
    if not has_work_experience_section(text):
        return "No experience section found in the resume."
    
    # Extract work experience
    experiences = extract_experience(text)
    
    if not experiences:
        return "No work experience entries found in the resume."
    
    return experiences

import re

def extract_skills(text):
    """Extract skills with strict pattern matching for predefined keywords."""
    # Predefined skill categories
    skill_categories = {
        "Programming Languages": [
            "python", "java", "c++", "c#", "javascript", "typescript", 
            "ruby", "php", "swift", "kotlin", "go", "rust", "scala"
        ],
        "Web Technologies": [
            "html", "css", "react", "angular", "vue", "django", 
            "flask", "nodejs", "express", "spring", ".net", "asp.net"
        ],
        "Databases": [
            "mysql", "postgresql", "mongodb", "sqlite", "oracle", 
            "sql", "nosql", "redis", "cassandra" , "Power BI", "Excel"
        ],
        "Cloud Platforms": [
            "aws", "azure", "google cloud", "heroku", "digital ocean", 
            "amazon web services", "cloud computing"
        ],
        "DevOps & Tools": [
            "docker", "kubernetes", "jenkins", "git", "github", 
            "gitlab", "ansible", "terraform", "ci/cd"
        ],
        "Machine Learning & AI": [
            "tensorflow", "pytorch", "scikit-learn", "keras", 
            "machine learning", "deep learning", "nlp", "computer vision"
        ],
        "Frameworks": [
            "spring boot", "django", "flask", "react", "angular", 
            "vue", "laravel", "symfony", "express"
        ]
    }

    # Combine keywords from all categories (already lowercased)
    all_keywords = [keyword.lower() for category in skill_categories.values() for keyword in category]

    skills = set()
    
    # Extract skills section
    skills_section, _ = extract_section(text, ["Skills", "Technical Skills", "Competencies", "Expertise"])
    
    if skills_section:
        skills_section_lower = skills_section.lower()
        for keyword in all_keywords:
            # Check for exact match of the keyword as a whole word/phrase
            if re.search(r'\b' + re.escape(keyword) + r'\b', skills_section_lower):
                skills.add(keyword)
        if skills:
            return list(skills)
    
    # Fallback: Search entire document
    text_lower = text.lower()
    for keyword in all_keywords:
        # Check for exact match of the keyword as a whole word/phrase
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            skills.add(keyword)
    
    return list(skills)

def generate_ats_score(parsed_data):
    """Generate a simple ATS score based on the extracted data."""
    score = 0
    max_score = 100
    
    # Check if we have basic contact information
    if parsed_data["contact_details"]["Name"] != "Not Found":
        score += 10
    if parsed_data["contact_details"]["Email"] != "Not Found":
        score += 10
    if parsed_data["contact_details"]["Phone"] != "Not Found":
        score += 10
        
    # Check education
    if parsed_data["education"] and len(parsed_data["education"]) > 0:
        score += 20
        
    # Check experience
    if parsed_data["experience"] and len(parsed_data["experience"]) > 0:
        score += 25
        
    # Check skills
    if parsed_data["skills"] and len(parsed_data["skills"]) > 0:
        score += 25
        
    return {
        "score": score,
        "max_score": max_score,
        "percentage": f"{score}%"
    }

# Added for root endpoint compatibility (for backward compatibility)
@app.route("/", methods=["POST"])
def root_upload():
    """Redirect root POST requests to the upload handler."""
    return upload_resume()

@app.route("/upload", methods=["POST"])
def upload_resume():
    """Handle resume upload(s) and return extracted data."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    files = request.files.getlist("file")
    
    if not files or len(files) == 0 or files[0].filename == "":
        return jsonify({"error": "No selected file"}), 400

    results = []
    
    for file in files:
        if not allowed_file(file.filename):
            return jsonify({"error": f"Invalid file type for {file.filename}. Only PDFs are allowed."}), 400
            
        try:
            # Save file temporarily
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(file_path)

            # Extract details
            text = extract_text_from_pdf(file_path)
            parsed_data = {
                "contact_details": extract_contact_details(text, file.filename),
                "education": extract_education(text),
                "experience": extract_experience(text),
                "skills": extract_skills(text)
            }
            
            # Generate ATS score
            ats_score = generate_ats_score(parsed_data)
            
            results.append({
                "filename": file.filename,
                "parsed_data": parsed_data,
                "ats_score": ats_score
            })

            # Cleanup uploaded file
            os.remove(file_path)

        except Exception as e:
            return jsonify({"error": f"Error processing file {file.filename}: {str(e)}"}), 500

    return jsonify(results), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)