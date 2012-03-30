import request_handler
import user_util
from models import Video
from app import App

class AboutRequestHandler(request_handler.RequestHandler):
    def render_jinja2_template(self, template_name, template_values):
        template_values["selected_nav_link"] = "about"
        request_handler.RequestHandler.render_jinja2_template(self, template_name, template_values)

class ViewAbout(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/about_the_site.html', {
            "selected_id": "the-site",
            "approx_vid_count": Video.approx_count(),
        })

class ViewAboutTheTeam(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/about_the_team.html', {"selected_id": "the-team"})

class ViewGettingStarted(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/getting_started.html', {
            "selected_id": "getting-started",
            "approx_vid_count": Video.approx_count(),
            "App": App
        })

class ViewDiscoveryLab(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/discovery_lab.html', {
            "selected_id": "discovery-lab"})

class ViewFAQ(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/faq.html', {
            "selected_id": "faq",
            "approx_vid_count": Video.approx_count()
        })

class ViewDownloads(AboutRequestHandler):
    @user_util.open_access
    def get(self):
        self.render_jinja2_template('about/downloads.html', {})
