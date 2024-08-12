from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
import requests
from django.contrib.auth.decorators import login_required
from .models import Course, Module, Lesson
from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Q
import os
import google.generativeai as genai
import re
import time
import uuid
from dotenv import load_dotenv


load_dotenv()


# Configure the Google Generative AI SDK
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

DEMO_VIDEO_URL = "https://synthesia-ttv-data.s3.amazonaws.com/video_data/7f3f3679-b252-4469-b742-a8f66d702abf/transfers/rendered_video.mp4?response-content-disposition=attachment%3Bfilename%3D%22Demo%20Video.mp4%22&AWSAccessKeyId=AKIA32NGJ5TSTZY6HDVC&Signature=y4EZC90j4EFljyscaQ6nZEUY2P8%3D&Expires=1723516425"
SYNTHESIA_API_KEY = os.getenv('SYNTESIA_API_KEY')

# Create your views here.
def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    else:
        return render(request, 'index.html')

def generate_lesson_video(lesson):
    # If it's the first lesson of the course, generate the video using Synthesia
    # I am only generating video for the first lesson to save funds
    if lesson.order != 1.1:
        # For other lessons, I will use the demo video to save funds
        lesson.video_url = DEMO_VIDEO_URL
        lesson.synthesia_video_id = "7f3f3679-b252-4469-b742-a8f66d702abf"
        lesson.video_status = 'complete'
        lesson.save()
    else:
        print(lesson.title)
        print(lesson.order)
        url = "https://api.synthesia.io/v2/videos"
        payload = {
            "test": True,  # Tomi, set to False in production
            "visibility": "private",
            "aspectRatio": "16:9",
            "title": f"{lesson.title}",
            "input": [
                {
                    "avatarSettings": {
                        "horizontalAlign": "center",
                        "scale": 1,
                        "style": "rectangular",
                        "seamless": False
                    },
                    "backgroundSettings": {
                        "videoSettings": {
                            "shortBackgroundContentMatchMode": "freeze",
                            "longBackgroundContentMatchMode": "trim"
                        }
                    },
                    "scriptText": lesson.video_transcript,
                    "avatar": "anna_costume1_cameraA",
                    "background": "green_screen"
                }
            ]
        }
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": SYNTHESIA_API_KEY
        }
        response = requests.post(url, json=payload, headers=headers)
        print(response.json())
        print(response.status_code)

        if response.status_code == 201:
            response_data = response.json()
            lesson.synthesia_video_id = response_data['id']
            lesson.video_status = 'in_progress'
            lesson.save()

        else:
            lesson.video_status = 'failed'
            lesson.save()

def check_video_status(lesson):
    if lesson.synthesia_video_id and not lesson.video_url:
        url = f"https://api.synthesia.io/v2/videos/{lesson.synthesia_video_id}"
        headers = {
            "accept": "application/json",
            "Authorization": SYNTHESIA_API_KEY
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            response_data = response.json()
            if response_data['status'] == 'complete':
                lesson.video_url = response_data['download']
                lesson.video_status = 'complete'
                lesson.save()
            elif response_data['status'] == 'failed':
                lesson.video_status = 'failed'
                lesson.save()

def dashboard(request):
    # Fetch courses where the user is the creator or an authorised user
    course_list = Course.objects.filter(
        Q(created_by=request.user) | Q(authorised_users=request.user)
    ).distinct()

    # Prepare a list to hold courses and their lesson counts
    updates_course_list = []
    
    for course in course_list:
        # Calculate the total number of lessons for the course
        total_lessons = Lesson.objects.filter(module__course=course).count()
        updates_course_list.append({
            'course': course,
            'total_lessons': total_lessons
        })

    return render(request, 'dashboard.html', {'updates_course_list': updates_course_list})



# This is using regex to parse, tbh I think this is better
def parse_modules_and_lessons(output):
    lines = output.split('\n')
    course_structure = {}
    current_module = None

    module_pattern = re.compile(r'^\**\s*Module \d+:')
    lesson_pattern = re.compile(r'^- Lesson \d+\.\d+:')

    for line in lines:
        line = line.strip()
        if module_pattern.match(line):
            current_module = re.sub(r'^\**\s*', '', line)  # Remove leading asterisks and spaces
            course_structure[current_module] = []
        elif lesson_pattern.match(line) and current_module:
            course_structure[current_module].append(line)

    return course_structure

def generate_short_description(course_info):
    generation_config = {
        "temperature": 0.7,  # Adjust for less randomness
        "top_p": 0.9,        # Use top-p sampling for better quality
        "top_k": 50,         # Use top-k sampling for better quality
        "max_output_tokens": 256,
        "response_mime_type": "text/plain",
    }

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config=generation_config,
    )

    chat_session = model.start_chat(
        history=[]
    )

    # Extract module titles
    module_titles = [module.title for module in course_info.modules.all()]

    # Create the prompt for generating the short description
    prompt = f"""
    Based on the following course information, generate a very short description (1 sentence). The response must contain only the generated description and nothing else.

    Course Title: {course_info.title}
    Skill Level: {course_info.skill_level}
    Language: {course_info.language}
    Number of Modules: {course_info.modules.count()}
    Number of Lessons: {sum([module.lessons.count() for module in course_info.modules.all()])}
    Module Titles: {', '.join(module_titles)}
    """

    response = chat_session.send_message(prompt)

    if response:
        return response.text.strip()
    else:
        return "Description not available"
    

def generate_long_description(course_info):
    generation_config = {
        "temperature": 0.7,  # Adjust for less randomness
        "top_p": 0.9,        # Use top-p sampling for better quality
        "top_k": 50,         # Use top-k sampling for better quality
        "max_output_tokens": 2000,
        "response_mime_type": "text/plain",
    }

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config=generation_config,
    )

    chat_session = model.start_chat(
        history=[]
    )

    # Extract module titles
    module_titles = [module.title for module in course_info.modules.all()]

    # Create the prompt for generating the long description
    prompt = f"""
    Based on the detailed course information provided below, generate a comprehensive description of the course. The description shoild be at least 1500 characters long. The response must contain only the generated description and nothing else. Use appropriate HTML tags like <p>, <strong>, etc., for formatting.

    Course Title: {course_info.title}
    Skill Level: {course_info.skill_level}
    Language: {course_info.language}
    Number of Modules: {course_info.modules.count()}
    Number of Lessons: {sum([module.lessons.count() for module in course_info.modules.all()])}
    Module Titles: {', '.join(module_titles)}
    """

    response = chat_session.send_message(prompt)

    if response:
        return response.text.strip()
    else:
        return "Description not available"
   

def generate_lesson_content(lesson):
    try:
        generation_config = {
            "temperature": 2.0,  
            "top_p": 0.9,        
            "top_k": 50,         
            "max_output_tokens": 8192,  
            "response_mime_type": "text/plain",
        }

        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            generation_config=generation_config,
        )

        chat_session = model.start_chat(
            history=[]
        )

        # Fetch previous lessons in the same module for context
        previous_lessons = Lesson.objects.filter(module=lesson.module, order__lt=lesson.order).order_by('order')
        previous_lessons_titles = [l.title for l in previous_lessons]

        # Create the prompt for generating the lesson content
        prompt = f"""
        Imagine you are creating a fresh, engaging lesson for someone who is entirely new to the topic of "{lesson.title}". The goal is to make the content interesting, original, and easy to understand.

        Break down the lesson into clearly defined sections. Each section should introduce, explain, and provide examples in a friendly and accessible tone. Ensure each section uses proper HTML tags for formatting.

        Use the following format strictly:

        **Intro Text**
        Wrap the introduction in <p> tags. Use <strong> tags to emphasize key concepts.

        **Talking Head Video Transcript**
        No HTML tags should be used here. This section should be plain text, as it will be spoken directly to the learner. Please ensure that the script addresses the learner by their first name, {lesson.module.course.created_by.first_name} in a conversational and engaging manner. 

        **Main Content**
        Use the following HTML structure:
        - Wrap paragraphs in <p> tags.
        - Use <h3> tags for subheadings.
        - Use <ul> and <li> tags for lists.
        - Wrap code examples in <pre><code> tags.

        **Interactive Task**
        - Provide clear instructions wrapped in <p> tags.
        - Use <ul> and <li> tags for task steps.
        - Provide the solution wrapped in <pre><code> tags.

        The content must be original and not similar to existing text to avoid recitation issues. Write in {lesson.module.course.language}.

        Course Title: {lesson.module.course.title}
        Module Title: {lesson.module.title}
        Previous Lessons: {', '.join(previous_lessons_titles)}
        Lesson Title: {lesson.title}
        Skill Level: {lesson.module.course.skill_level}
        Language: {lesson.module.course.language}
        """



        response = chat_session.send_message(prompt)

        if response:
            return response.text.strip()
        else:
            return None
        
    except Exception as e:
        # Log the error for debugging purposes
        print(f"Error generating content for lesson {lesson.title}: {str(e)}")
        # Return a blank response if an error occurs
        return ""


def parse_lesson_content(response):
    # Normalize line endings
    response = response.replace("\r\n", "\n").replace("\r", "\n")
    
    # Define start markers for each section, allowing for 0 or more special characters
    section_markers = {
        "intro_text": r"^[\*\#\s]*Intro Text[\*\#\s]*$",
        "video_transcript": r"^[\*\#\s]*Talking Head Video Transcript[\*\#\s]*$",
        "main_content": r"^[\*\#\s]*Main Content[\*\#\s]*$",
        "interactive_task": r"^[\*\#\s]*Interactive Task[\*\#\s]*$"
    }

    # Initialize a dictionary to store the sections
    sections = {
        "intro_text": "",
        "video_transcript": "",
        "main_content": "",
        "interactive_task": ""
    }

    # Split the response into lines for easier processing
    lines = response.split("\n")
    current_section = None

    # Iterate through each line to identify and capture sections
    for line in lines:
        line_stripped = line.strip()
        found_section = False

        # Check if the line matches any section marker
        for section, pattern in section_markers.items():
            if re.match(pattern, line_stripped, re.IGNORECASE):
                current_section = section
                found_section = True
                break
        
        # If it's not a section header, add content to the current section
        if not found_section and current_section:
            sections[current_section] += line + "\n"

    # Clean up the section content by stripping excess whitespace
    for key in sections:
        sections[key] = sections[key].strip()

    return sections

@login_required(login_url="/login")
def new_course(request):
    if request.method == 'POST':
        title = request.POST.get('course_title')
        skill_level = request.POST.get('skill_level')
        language = request.POST.get('language')

        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }

        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
        )

        chat_session = model.start_chat(
            history=[]
        )

        prompt = f"""
        Create a detailed course curriculum outline. The course title, skill level, and the preferred language for the lesson titles will be provided. The course outline should be structured into modules, each containing a list of detailed lesson titles. The lesson titles should be clear, concise, and progressively structured to cover the essential topics of the course. The response must contain only the module and lesson titles in the following format and nothing else:

        Module 1: [Module Title]
        - Lesson 1.1: [Detailed Lesson Title]
        - Lesson 1.2: [Detailed Lesson Title]
        - Lesson 1.3: [Detailed Lesson Title]
        ...

        Module 2: [Module Title]
        - Lesson 2.1: [Detailed Lesson Title]
        - Lesson 2.2: [Detailed Lesson Title]
        - Lesson 2.3: [Detailed Lesson Title]
        ...

        Course Title: {title}
        Skill Level: {skill_level}
        Language: {language}
        """

        response = chat_session.send_message(prompt)

        if response:
            course_content = response.text.strip()
            parsed_content = parse_modules_and_lessons(course_content)

            course = Course.objects.create(
                title=title,
                skill_level=skill_level,
                language=language,
                created_by=request.user,
                image_url="https://s3.eu-west-2.amazonaws.com/ariel-production/course-thumbnails/561543076240831.png"
            )

            course.authorised_users.add(request.user)

            for module_title, lessons in parsed_content.items():
                try:
                    module_order = int(module_title.split(' ')[1].strip(':'))
                    module_title_clean = module_title.split(': ', 1)[1]
                    module = Module.objects.create(course=course, title=module_title_clean, order=module_order)

                    for lesson in lessons:
                        try:
                            lesson_number = lesson.split(' ')[2].strip(':')  # Extract lesson number
                            lesson_order = float(lesson_number)
                            lesson_title = lesson.split(': ', 1)[1]
                            lesson_instance = Lesson.objects.create(module=module, title=lesson_title, order=lesson_order)

                            # Generate and save lesson content
                            lesson_content = generate_lesson_content(lesson_instance)
                            if lesson_content:
                                # Parse and save the lesson content
                                print("About to parse content")
                                parsed_content = parse_lesson_content(lesson_content)
                                
                                # print(parsed_content)
                                lesson_instance.raw_content = lesson_content
                                lesson_instance.intro_text = parsed_content["intro_text"]
                                lesson_instance.video_transcript = parsed_content["video_transcript"]
                                lesson_instance.main_content = parsed_content["main_content"]
                                lesson_instance.interactive_task = parsed_content["interactive_task"]
                                lesson_instance.save()

                                
                                generate_lesson_video(lesson_instance)

                            time.sleep(1)
                        except (ValueError, IndexError) as e:
                            # Handle the specific error in lesson parsing
                            print(f"Error parsing lesson: {lesson}, Error: {e}")

                except (ValueError, IndexError) as e:
                    # Handle the specific error in module parsing
                    print(f"Error parsing module: {module_title}, Error: {e}")

            # Generate and save the short description
            short_description = generate_short_description(course)
            course.short_description = short_description
            course.save()

            # Generate and save the long description
            long_description = generate_long_description(course)
            course.long_description = long_description
            course.save()

            return redirect('course_detail', pk=course.pk)
        else:
            return render(request, 'new-course.html', {'error': 'Error generating course content. Please try again.'})

    return render(request, 'new-course.html')

@login_required(login_url="/login")
def course_detail(request, pk):
    course_info = get_object_or_404(Course, id=pk)

    if request.user != course_info.created_by and not course_info.authorised_users.filter(id=request.user.id).exists():
        return redirect("/")


    modules = Module.objects.filter(course=course_info).order_by('order')
    module_lessons = {}
    lessons_count = 0
    
    # Variable to track the highest ordered lesson completed by the user
    highest_completed_lesson = None

    for module in modules:
        lessons = Lesson.objects.filter(module=module).order_by('order')
        module_lessons[module] = lessons
        lessons_count += lessons.count()

        # Check for the highest ordered completed lesson by the user
        for lesson in lessons:
            if request.user in lesson.completed_by.all():
                if not highest_completed_lesson or lesson.order > highest_completed_lesson.order:
                    highest_completed_lesson = lesson

    # Determine the button text and URL
    if highest_completed_lesson:
        # User has completed at least one lesson
        button_text = "Continue Course"
        next_lesson = highest_completed_lesson.get_next_lesson()
        button_url = next_lesson.get_absolute_url() if next_lesson else highest_completed_lesson.get_absolute_url()
    else:
        # User hasn't completed any lessons, start from the first lesson
        first_lesson = Lesson.objects.filter(module__course=course_info).order_by('module__order', 'order').first()
        button_text = "Start Course"
        button_url = first_lesson.get_absolute_url() if first_lesson else "#"

    context = {
        'course': course_info, 
        'modules': module_lessons, 
        'lessons_count': lessons_count,
        'button_text': button_text,
        'button_url': button_url
    }
    
    return render(request, 'course-detail.html', context)


# def lesson(request, pk):
#     lesson_object = Lesson.objects.get(id=pk)
#     module_object = lesson_object.module
#     course_object = module_object.course

#     modules = Module.objects.filter(course=course_object).order_by('order')
    
#     course_structure = {}
#     for module in modules:
#         lessons = Lesson.objects.filter(module=module).order_by('order')
#         course_structure[module] = lessons

#     context = {
#         'lesson': lesson_object,
#         'course_structure': course_structure,
#     }

#     return render(request, 'lesson.html', context)


def lesson(request, pk):
    # Fetch the lesson object
    lesson_object = get_object_or_404(Lesson, id=pk)

    check_video_status(lesson_object)

    # Fetch the module and course for the current lesson
    module_object = lesson_object.module
    course_object = module_object.course

    # Check if the user is either the creator or in the list of authorized users
    if request.user != course_object.created_by and not course_object.authorised_users.filter(id=request.user.id).exists():
        return redirect('/')


    # Check if the lesson content is missing
    if not lesson_object.intro_text or not lesson_object.main_content or not lesson_object.video_transcript or not lesson_object.interactive_task:
        # Generate the content if any of the fields are missing
        raw_content = generate_lesson_content(lesson_object)
        print('This is raw content')
        print(raw_content)
        if raw_content:
            # Parse the generated content
            parsed_content = parse_lesson_content(raw_content)
            print('This is parsed content')
            print(parsed_content)
            # Update the lesson object with the parsed content
            lesson_object.raw_content = raw_content
            lesson_object.intro_text = parsed_content.get('intro_text', '')
            lesson_object.video_transcript = parsed_content.get('video_transcript', '')
            lesson_object.main_content = parsed_content.get('main_content', '')
            lesson_object.interactive_task = parsed_content.get('interactive_task', '')
            lesson_object.save()

    # Fetch the module and course for the current lesson
    module_object = lesson_object.module
    course_object = module_object.course

    # Build the course structure
    modules = Module.objects.filter(course=course_object).order_by('order')
    
    course_structure = {}
    for module in modules:
        lessons = Lesson.objects.filter(module=module).order_by('order')
        course_structure[module] = lessons

    
    all_lessons = Lesson.objects.filter(module__course=course_object).order_by('module__order', 'order')
    lesson_index = list(all_lessons).index(lesson_object)

    previous_lesson = all_lessons[lesson_index - 1] if lesson_index > 0 else None
    next_lesson = all_lessons[lesson_index + 1] if lesson_index < len(all_lessons) - 1 else None


    # Pass the context to the template
    context = {
        'lesson': lesson_object,
        'course_structure': course_structure,
        'previous_lesson': previous_lesson,
        'next_lesson': next_lesson,
    }

    return render(request, 'lesson.html', context)

@login_required(login_url="/login")
def toggle_lesson_completion(request, pk):
    lesson = get_object_or_404(Lesson, id=pk)
    user = request.user

    if user in lesson.completed_by.all():
        lesson.completed_by.remove(user)
        status = 'incomplete'
    else:
        lesson.completed_by.add(user)
        status = 'complete'

    return JsonResponse({'status': status})

def access_course(request):
    if request.method == 'POST':
        course_code = request.POST.get('course_code')

        try:
            course_code_uuid = uuid.UUID(course_code)
            course = Course.objects.get(course_code=course_code_uuid)
            
            if request.user not in course.authorised_users.all():
                course.authorised_users.add(request.user)
                course.save()
                messages.success(request, 'You have successfully gained access to the course.')
                return redirect('course_detail', pk=course.id)
            else:
                messages.info(request, 'You already have access to this course.')
                return render(request, 'access-course.html')

        except ValueError:
            # If the provided course code is not a valid UUID
            messages.error(request, 'Invalid course code format. Please enter a valid course code.')

        except Course.DoesNotExist:
            # If no course is found with the provided course code
            messages.error(request, 'Invalid course code. Please try again.')
            return render(request, 'access-course.html')

    return render(request, 'access-course.html')

def login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            auth_login(request, user)
            return redirect('index')
        else:
            messages.error(request, "Invalid email or password")
            return render(request, 'sign-in.html')
    
    return render(request, 'sign-in.html')


def signup(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        
        if password != password2:
            messages.error(request, "Passwords do not match")
            return render(request, 'sign-up.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email is already taken")
            return render(request, 'sign-up.html')
        
        user = User.objects.create_user(username=email, email=email, password=password)
        user.first_name = first_name
        user.save()

        user = authenticate(username=email, password=password)
        if user is not None:
            auth_login(request, user)
            return redirect('index')

        messages.error(request, "Failed to authenticate user")
        return render(request, 'sign-up.html')

    return render(request, 'sign-up.html')


def logout(request):
    auth_logout(request)
    return redirect('index')
