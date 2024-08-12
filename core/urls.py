from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('new-course', views.new_course, name='new-course'),
    path('access-course', views.access_course, name='access-course'),
    path('course_detail/<str:pk>/', views.course_detail, name='course_detail'),
    path('lesson/<str:pk>/', views.lesson, name='lesson'),
    path('toggle-lesson-completion/<str:pk>/', views.toggle_lesson_completion, name='toggle-lesson-completion'),
    path('login', views.login, name='login'),
    path('signup', views.signup, name='signup'),
    path('logout', views.logout, name='logout'),
]