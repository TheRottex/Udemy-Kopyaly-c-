"""Platform adaptör arayüzü. Yeni bir platform için PlatformAdapter'dan türetip
platforms/<ad>.py içinde `ADAPTERS = [Sinifiniz()]` tanımlayın (README'ye bakın)."""
from dataclasses import dataclass, field

from .resources import ResourceLink, find_resources
from .sniffer import MediaSniffer, VideoSource


@dataclass
class Course:
    title: str
    url: str
    thumb: str = ""


@dataclass
class Lesson:
    title: str
    url: str


@dataclass
class Section:
    title: str
    lessons: list = field(default_factory=list)


@dataclass
class CourseInfo:
    title: str
    sections: list
    course_resources: list = field(default_factory=list)


@dataclass
class LessonInfo:
    video: VideoSource
    resources: list


class ConfigError(Exception):
    pass


class PlatformAdapter:
    id = "base"
    name = "Base"
    login_url = ""
    configurable = False

    def search_courses(self, ctx, query: str) -> list:
        raise NotImplementedError

    def list_course(self, ctx, course_url: str) -> CourseInfo:
        raise NotImplementedError

    def find_video(self, page, sniffer: MediaSniffer) -> VideoSource:
        """Ders sayfası açıldıktan sonra video kaynağını bulur (sniffer navigasyondan önce bağlanır)."""
        raise NotImplementedError

    def find_resources(self, page) -> list:
        """Ders sayfasındaki ek dosyalar. Varsayılan: sezgisel 'Kaynaklar' bulma."""
        return find_resources(page)

    def inspect_lesson(self, ctx, lesson_url: str) -> LessonInfo:
        page = ctx.new_page()
        try:
            sniffer = MediaSniffer(page)
            page.goto(lesson_url, wait_until="domcontentloaded")
            video = self.find_video(page, sniffer)
            resources = self.find_resources(page)
            return LessonInfo(video, resources)
        finally:
            page.close()
