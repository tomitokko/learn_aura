from django.db import models
from django.contrib.auth.models import User
import uuid
from datetime import date
from django.urls import reverse



class Course(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_code = models.UUIDField(default=uuid.uuid4)
    title = models.CharField(max_length=255)
    skill_level = models.CharField(max_length=50)
    language = models.CharField(max_length=50)
    created_by = models.ForeignKey(User, related_name='courses', on_delete=models.CASCADE)
    image_url = models.URLField(max_length=200, blank=True)
    created_date = models.DateField(default=date.today)
    short_description = models.TextField(blank=True, null=True)
    long_description = models.TextField(blank=True, null=True)
    authorised_users = models.ManyToManyField(User, related_name='authorised_user', blank=True)

    def __str__(self):
        return self.title

class Module(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, related_name='modules', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'{self.order}. {self.title}'

class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, related_name='lessons', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    order = models.FloatField()
    raw_content = models.TextField(blank=True, null=True)
    intro_text = models.TextField(blank=True, null=True)
    video_transcript = models.TextField(blank=True, null=True)
    main_content = models.TextField(blank=True, null=True)
    interactive_task = models.TextField(blank=True, null=True)
    completed_by = models.ManyToManyField(User, related_name='completed_lessons', blank=True)
    video_url = models.URLField(max_length=10000, blank=True, null=True)
    video_status = models.CharField(max_length=50, blank=True, null=True)
    synthesia_video_id = models.CharField(max_length=3000, blank=True, null=True)

    class Meta:
        ordering = ['order']

    def get_next_lesson(self):
        # Find the next lesson within the same module
        next_lesson = Lesson.objects.filter(module=self.module, order__gt=self.order).order_by('order').first()
        # If there's no next lesson in the same module, check the next module
        if not next_lesson:
            next_module = Module.objects.filter(course=self.module.course, order__gt=self.module.order).order_by('order').first()
            if next_module:
                next_lesson = Lesson.objects.filter(module=next_module).order_by('order').first()
        return next_lesson

    def get_absolute_url(self):
        return reverse('lesson', args=[str(self.id)])

    def __str__(self):
        return f'{self.order}. {self.title}'