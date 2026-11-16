"""
The reference PDFs' wording a syllabus takes where the Admin leaves a line
empty: the line under the title follows the structure, the packages page's
heading the title, and the inclusions the board. A revision stores an empty
subtitle or package title as empty -- "use the default" -- so the default keeps
following its title and structure; the default is worked out each time it is
shown or drawn, from the revision's own (immutable, once published) content.
"""
from .models import PACKAGE_TITLE_CHARS, Structure

SUBTITLES = {
    Structure.CHAPTER_WISE: 'Detailed Chapter-Wise 1:1 Learning Plan',
    Structure.BRIDGE_COURSE: 'Detailed Bridge Course Curriculum',
}
PACKAGE_TITLE_SUFFIX = ' – 1:1 Tuition Packages & Fee Details'


def subtitle_of(content):
    """The line under the title: the Admin's, or the structure's reference wording."""
    return content['subtitle'] or SUBTITLES[content['structure']]


def package_title_of(content):
    """The packages page's heading: the Admin's, or '<title> – 1:1 Tuition Packages & Fee Details'."""
    return content['package_title'] or f"{content['title']}{PACKAGE_TITLE_SUFFIX}"[:PACKAGE_TITLE_CHARS]


def default_inclusions(board):
    return ['Personalized 1:1 live sessions', f'Structured {board} aligned learning', 'Dedicated mentor support']
