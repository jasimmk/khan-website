"""Holds Video, VideoSubtitles, VideoLog, UserVideo, and UserVideoCSS.

(Also holds VideoSubtitlesFetchReport, though maybe that should go
somewhere else...)

Video: database entity about a single video
VideoSubtitles: database entity about subtitles for a single youtube video
VideoSubtitlesFetchReport: db entity about fetching from Universal Subtitles
VideoLog: db entity about how much of a single video a single user has watched
UserVideo: database entity about a single user interacting with a single video
UserVideoCSS: Marcia sez: 'joel's thingie responsible for the green checkmarks
   or blue circles by video titles'


A 'video' is what's on a Khan page like
   http://www.khanacademy.org/math/algebra/introduction-to-algebra/v/the-beauty-of-algebra
"""

import cPickle as pickle
import datetime
import logging
try:
    import json                  # python 2.6 and later
except ImportError:
    import simplejson as json    # python 2.5 and earlier

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import deferred

import app
import backup_model
import classtime
import consts
import experiments
import gae_bingo.gae_bingo
import goals.models
import image_cache
import layer_cache
import object_property
import points
import search
import setting_model
import shared_jinja
import summary_log_models
import user_models
import util

class Video(search.Searchable, db.Model):
    youtube_id = db.StringProperty()
    url = db.StringProperty()
    title = db.StringProperty()
    description = db.TextProperty()
    keywords = db.StringProperty()
    duration = db.IntegerProperty(default=0)

    # A dict of properties that may only exist on some videos such as
    # original_url for smarthistory_videos.
    extra_properties = object_property.UnvalidatedObjectProperty()

    # Human readable, unique id that can be used in URLS.
    readable_id = db.StringProperty()

    # List of parent topics
    topic_string_keys = object_property.TsvProperty(indexed=False)

    # YouTube view count from last sync.
    views = db.IntegerProperty(default=0)

    # Date first added via KA library sync with YouTube.
    # This property hasn't always existsed, so for many old videos
    # this date may be much later than the actual YouTube upload date.
    date_added = db.DateTimeProperty(auto_now_add=True)

    # List of currently available downloadable formats for this video
    downloadable_formats = object_property.TsvProperty(indexed=False)

    _serialize_blacklist = ["downloadable_formats", "topic_string_keys"]

    INDEX_ONLY = ['title', 'keywords', 'description']
    INDEX_TITLE_FROM_PROP = 'title'
    INDEX_USES_MULTI_ENTITIES = False

    @staticmethod
    def get_relative_url(readable_id):
        return '/video/%s' % readable_id

    @property
    def relative_url(self):
        return Video.get_relative_url(self.readable_id)

    @property
    def ka_url(self):
        return util.absolute_url(self.relative_url)

    @property
    def download_urls(self):

        if self.downloadable_formats:

            # We now serve our downloads from s3. Our old archive URL template is...
            #   "http://www.archive.org/download/KA-converted-%s/%s.%s"
            # ...which we may want to fall back on in the future should s3 prices climb.

            url_template = "http://s3.amazonaws.com/KA-youtube-converted/%s.%s/%s.%s"
            url_dict = {}

            for suffix in self.downloadable_formats:
                folder_suffix = suffix

                if suffix == "png":
                    # Special case: our pngs are generated during mp4 creation
                    # and they are in the mp4 subfolders
                    folder_suffix = "mp4"

                url_dict[suffix] = url_template % (self.youtube_id, folder_suffix, self.youtube_id, suffix)

            return url_dict

        return None

    def download_video_url(self):
        download_urls = self.download_urls
        if download_urls:
            return download_urls.get("mp4")
        return None

    @staticmethod
    def youtube_thumbnail_urls(youtube_id):

        # You might think that hq > sd, but you'd be wrong -- hqdefault is 480x360;
        # sddefault is 640x480. Unfortunately, not all videos have the big one.
        hq_youtube_url = "http://img.youtube.com/vi/%s/hqdefault.jpg" % youtube_id
        sd_youtube_url = "http://img.youtube.com/vi/%s/sddefault.jpg" % youtube_id

        return {
                "hq": hq_youtube_url,
                "sd": image_cache.ImageCache.url_for(sd_youtube_url, fallback_url=hq_youtube_url),
        }

    @staticmethod
    def get_for_readable_id(readable_id, version=None):
        video = None
        query = Video.all()
        query.filter('readable_id =', readable_id)
        # The following should just be:
        # video = query.get()
        # but the database currently contains multiple Video objects for a particular
        # video.  Some are old.  Some are due to a YouTube sync where the youtube urls
        # changed and our code was producing youtube_ids that ended with '_player'.
        # This hack gets the most recent valid Video object.
        key_id = 0
        for v in query:
            if v.key().id() > key_id and not v.youtube_id.endswith('_player'):
                video = v
                key_id = v.key().id()
        # End of hack

        # if there is a version check to see if there are any updates to the video
        if version:
            # TODO(csilvers): get rid of circular dependency here
            import topic_models
            if video:
                change = topic_models.VersionContentChange.get_change_for_content(video, version)
                if change:
                    video = change.updated_content(video)

            # if we didnt find any video, check to see if another video's readable_id has been updated to the one we are looking for
            else:
                changes = topic_models.VersionContentChange.get_updated_content_dict(version)
                for key, content in changes.iteritems():
                    if (type(content) == Video and
                        content.readable_id == readable_id):
                        video = content
                        break

        return video

    @staticmethod
    @layer_cache.cache_with_key_fxn(
        lambda : "Video.get_all_%s" % (setting_model.Setting.cached_content_add_date()),
        layer=layer_cache.Layers.Memcache)
    def get_all():
        return Video.all().fetch(100000)

    @staticmethod
    def get_all_live(version=None):
        # TODO(csilvers): get rid of circular dependency here
        import topic_models
        if not version:
            version = topic_models.TopicVersion.get_default_version()

        root = topic_models.Topic.get_root(version)
        videos = root.get_videos(include_descendants=True, include_hidden=False)

        # return only unique videos
        video_dict = dict((v.key(), v) for v in videos)
        return video_dict.values()

    def has_topic(self):
        return bool(self.topic_string_keys)

    # returns the first non-hidden topic
    def first_topic(self):
        if self.topic_string_keys:
            return db.get(self.topic_string_keys[0])
        return None

    def current_user_points(self):
        user_video = UserVideo.get_for_video_and_user_data(self, user_models.UserData.current())
        if user_video:
            return points.VideoPointCalculator(user_video)
        else:
            return 0

    @staticmethod
    def get_dict(query, fxn_key):
        video_dict = {}
        for video in query.fetch(10000):
            video_dict[fxn_key(video)] = video
        return video_dict

    @layer_cache.cache_with_key_fxn(
        lambda self: "related_exercises_%s" % self.key(),
        layer=layer_cache.Layers.Memcache,
        expiration=3600 * 2)
    def related_exercises(self):
        # TODO(csilvers): get rid of circular dependency here
        import exercise_video_model
        exvids = exercise_video_model.ExerciseVideo.all()
        exvids.filter('video =', self.key())
        exercises = [ev.exercise for ev in exvids]
        exercises.sort(key=lambda e: e.h_position)
        exercises.sort(key=lambda e: e.v_position)
        return exercises

    @staticmethod
    @layer_cache.cache(expiration=3600)
    def approx_count():
        return int(setting_model.Setting.count_videos()) / 100 * 100

    # Gets the data we need for the video player
    @staticmethod
    def get_play_data(readable_id, topic, discussion_options):
        # TODO(csilvers): get rid of circular dependency here
        import topic_models

        video = None

        # If we got here, we have a readable_id and a topic, so we can display
        # the topic and the video in it that has the readable_id.  Note that we don't
        # query the Video entities for one with the requested readable_id because in some
        # cases there are multiple Video objects in the datastore with the same readable_id
        # (e.g. there are 2 "Order of Operations" videos).
        videos = topic_models.Topic.get_cached_videos_for_topic(topic)
        previous_video = None
        next_video = None
        for v in videos:
            if v.readable_id == readable_id:
                v.selected = 'selected'
                video = v
            elif video is None:
                previous_video = v
            else:
                next_video = v
                break

        if video is None:
            return None

        previous_video_dict = {
            "readable_id": previous_video.readable_id,
            "key_id": previous_video.key().id(),
            "title": previous_video.title
        } if previous_video else None

        next_video_dict = {
            "readable_id": next_video.readable_id,
            "key_id": next_video.key().id(),
            "title": next_video.title
        } if next_video else None

        if app.App.offline_mode:
            video_path = "/videos/" + _get_mangled_topic_name(topic.id) + "/" + video.readable_id + ".flv"
        else:
            video_path = video.download_video_url()

        if video.description == video.title:
            video.description = None

        related_exercises = video.related_exercises()
        button_top_exercise = None
        if related_exercises:
            def ex_to_dict(exercise):
                return {
                    'name': exercise.display_name,
                    'url': exercise.relative_url,
                }
            button_top_exercise = ex_to_dict(related_exercises[0])

        user_video = UserVideo.get_for_video_and_user_data(video, user_models.UserData.current())

        awarded_points = 0
        if user_video:
            awarded_points = user_video.points

        subtitles_key_name = VideoSubtitles.get_key_name('en', video.youtube_id)
        subtitles = VideoSubtitles.get_by_key_name(subtitles_key_name)
        subtitles_json = None
        show_interactive_transcript = False
        if subtitles:
            subtitles_json = subtitles.load_json()
            transcript_alternative = experiments.InteractiveTranscriptExperiment.ab_test()
            show_interactive_transcript = (transcript_alternative == experiments.InteractiveTranscriptExperiment.SHOW)

        # TODO (tomyedwab): This is ugly; we would rather have these templates client-side.
        player_html = shared_jinja.get().render_template('videoplayer.html',
            user_data=user_models.UserData.current(), video_path=video_path, video=video,
            awarded_points=awarded_points, video_points_base=consts.VIDEO_POINTS_BASE,
            subtitles_json=subtitles_json, show_interactive_transcript=show_interactive_transcript)

        discussion_html = shared_jinja.get().render_template('videodiscussion.html',
            user_data=user_models.UserData.current(), video=video, topic=topic, **discussion_options)

        subtitles_html = shared_jinja.get().render_template('videosubtitles.html',
            subtitles_json=subtitles_json)

        return {
            'title': video.title,
            'extra_properties': video.extra_properties or {},
            'description': video.description,
            'youtube_id': video.youtube_id,
            'readable_id': video.readable_id,
            'key': unicode(video.key()),
            'video_path': video_path,
            'button_top_exercise': button_top_exercise,
            'related_exercises': [], # disabled for now
            'previous_video': previous_video_dict,
            'next_video': next_video_dict,
            'selected_nav_link': 'watch',
            'issue_labels': ('Component-Videos,Video-%s' % readable_id),
            'author_profile': 'https://plus.google.com/103970106103092409324',
            'player_html': player_html,
            'discussion_html': discussion_html,
            'subtitles_html': subtitles_html,
            'videoPoints': awarded_points,
        }
    
    @staticmethod
    def reindex(video_list=None):
        """ Reindex Videos for search page """
        if video_list is None:
            video_list = Video.get_all_live()

        num_videos = len(video_list)
        for i, video in enumerate(video_list):
            logging.info("Indexing video %i/%i: %s (%s)" % 
                         (i, num_videos, video.title, video.key()))

            video.index()
            video.indexed_title_changed()

class VideoSubtitles(db.Model):
    """Subtitles for a YouTube video

    This is a cache of the content from Universal Subtitles for a video. A job
    runs periodically to keep these up-to-date.

    Store with a key name of "LANG:YOUTUBEID", e.g., "en:9Ek61w1LxSc".
    """
    modified = db.DateTimeProperty(auto_now=True, indexed=False)
    youtube_id = db.StringProperty()
    language = db.StringProperty()
    json = db.TextProperty()

    @staticmethod
    def get_key_name(language, youtube_id):
        return '%s:%s' % (language, youtube_id)

    def load_json(self):
        """Return subtitles JSON as a Python object

        If there is an issue loading the JSON, None is returned.
        """
        try:
            return json.loads(self.json)
        except ValueError:
            logging.warn('VideoSubtitles.load_json: json decode error')


class VideoSubtitlesFetchReport(db.Model):
    """Report on fetching of subtitles from Universal Subtitles

    Jobs that fail or are cancelled from the admin interface leave a hanging
    status since there's no callback to update the report.

    Store with a key name of JOB_NAME. Usually this is the UUID4 used by the
    task chain for processing. The key name is displayed as the report name.
    """
    created = db.DateTimeProperty(auto_now_add=True)
    modified = db.DateTimeProperty(auto_now=True, indexed=False)
    status = db.StringProperty(indexed=False)
    fetches = db.IntegerProperty(indexed=False)
    writes = db.IntegerProperty(indexed=False)
    errors = db.IntegerProperty(indexed=False)
    redirects = db.IntegerProperty(indexed=False)
    

def _commit_video_log(video_log, user_data=None):
    """Used by our deferred video log insertion process."""
    video_log.put()


def commit_log_summary_coaches(activity_log, coaches):
    """Used by our deferred log summary insertion process."""
    for coach in coaches:
        summary_log_models.LogSummary.add_or_update_entry(user_models.UserData.get_from_db_key_email(coach), activity_log, classtime.ClassDailyActivitySummary, summary_log_models.LogSummaryTypes.CLASS_DAILY_ACTIVITY, 1440)


class VideoLog(backup_model.BackupModel):
    user = db.UserProperty()
    video = db.ReferenceProperty(Video)
    video_title = db.StringProperty(indexed=False)

    # Use youtube_id since readable_id may have changed
    # by the time this VideoLog is retrieved
    youtube_id = db.StringProperty(indexed=False)

    # The timestamp corresponding to when this entry was created.
    time_watched = db.DateTimeProperty(auto_now_add=True)
    seconds_watched = db.IntegerProperty(default=0, indexed=False)

    # Most recently watched second in video (playhead state)
    last_second_watched = db.IntegerProperty(indexed=False)
    points_earned = db.IntegerProperty(default=0, indexed=False)
    playlist_titles = db.StringListProperty(indexed=False)

    # Indicates whether or not the video is deemed "complete" by the user.
    # This does not mean that this particular log was the one that resulted
    # in the completion - just that the video has been complete at some point.
    is_video_completed = db.BooleanProperty(indexed=False)

    _serialize_blacklist = ["video"]

    @staticmethod
    def get_for_user_data_between_dts(user_data, dt_a, dt_b):
        query = VideoLog.all()
        query.filter('user =', user_data.user)

        query.filter('time_watched >=', dt_a)
        query.filter('time_watched <=', dt_b)
        query.order('time_watched')

        return query

    @staticmethod
    def get_for_user_data_and_video(user_data, video):
        query = VideoLog.all()

        query.filter('user =', user_data.user)
        query.filter('video =', video)

        query.order('time_watched')

        return query

    @staticmethod
    def add_entry(user_data, video, seconds_watched, last_second_watched, detect_cheat=True):

        # TODO(csilvers): get rid of circular dependency here
        import badges.last_action_cache
        user_video = UserVideo.get_for_video_and_user_data(video, user_data, insert_if_missing=True)

        # Cap seconds_watched at duration of video
        seconds_watched = max(0, min(seconds_watched, video.duration))

        video_points_previous = points.VideoPointCalculator(user_video)

        action_cache = badges.last_action_cache.LastActionCache.get_for_user_data(user_data)

        last_video_log = action_cache.get_last_video_log()

        # If the last video logged is not this video and the times being credited
        # overlap, don't give points for this video. Can only get points for one video
        # at a time.
        if (detect_cheat and
                last_video_log and
                last_video_log.key_for_video() != video.key()):
            dt_now = datetime.datetime.now()
            other_video_time = last_video_log.time_watched
            this_video_time = dt_now - datetime.timedelta(seconds=seconds_watched)
            if other_video_time > this_video_time:
                logging.warning("Detected overlapping video logs " +
                                "(user may be watching multiple videos?)")
                return (None, None, 0, False)

        video_log = VideoLog()
        video_log.user = user_data.user
        video_log.video = video
        video_log.video_title = video.title
        video_log.youtube_id = video.youtube_id
        video_log.seconds_watched = seconds_watched
        video_log.last_second_watched = last_second_watched

        if seconds_watched > 0:
            # TODO(csilvers): get rid of circular dependencies here
            import badges.util_badges
            import topic_models

            if user_video.seconds_watched == 0:
                user_data.uservideocss_version += 1
                UserVideoCss.set_started(user_data, user_video.video, user_data.uservideocss_version)

            user_video.seconds_watched += seconds_watched
            user_data.total_seconds_watched += seconds_watched

            # Update seconds_watched of all associated topics
            video_topics = db.get(video.topic_string_keys)

            first_topic = True
            for topic in video_topics:
                user_topic = topic_models.UserTopic.get_for_topic_and_user_data(topic, user_data, insert_if_missing=True)
                user_topic.title = topic.standalone_title
                user_topic.seconds_watched += seconds_watched
                user_topic.last_watched = datetime.datetime.now()
                user_topic.put()

                video_log.playlist_titles.append(user_topic.title)

                if first_topic:
                    action_cache.push_video_log(video_log)

                badges.util_badges.update_with_user_topic(
                        user_data,
                        user_topic,
                        include_other_badges=first_topic,
                        action_cache=action_cache)

                first_topic = False

        user_video.last_second_watched = last_second_watched
        user_video.last_watched = datetime.datetime.now()
        user_video.duration = video.duration

        user_data.record_activity(user_video.last_watched)

        video_points_total = points.VideoPointCalculator(user_video)
        video_points_received = video_points_total - video_points_previous

        just_finished_video = False
        if not user_video.completed and video_points_total >= consts.VIDEO_POINTS_BASE:
            just_finished_video = True
            user_video.completed = True
            user_data.videos_completed = -1

            user_data.uservideocss_version += 1
            UserVideoCss.set_completed(user_data, user_video.video, user_data.uservideocss_version)

            gae_bingo.gae_bingo.bingo([
                'videos_finished',
                'struggling_videos_finished',
            ])
        video_log.is_video_completed = user_video.completed

        goals_updated = goals.models.GoalList.update_goals(user_data,
            lambda goal: goal.just_watched_video(user_data, user_video, just_finished_video))

        if video_points_received > 0:
            video_log.points_earned = video_points_received
            user_data.add_points(video_points_received)

        db.put([user_video, user_data])

        # Defer the put of VideoLog for now, as we think it might be causing hot tablets
        # and want to shift it off to an automatically-retrying task queue.
        # http://ikaisays.com/2011/01/25/app-engine-datastore-tip-monotonically-increasing-values-are-bad/
        deferred.defer(_commit_video_log, video_log,
                       _queue="video-log-queue",
                       _url="/_ah/queue/deferred_videolog")


        if user_data is not None and user_data.coaches:
            # Making a separate queue for the log summaries so we can clearly see how much they are getting used
            deferred.defer(commit_log_summary_coaches, video_log, user_data.coaches,
                _queue="log-summary-queue",
                _url="/_ah/queue/deferred_log_summary")

        return (user_video, video_log, video_points_total, goals_updated)

    def time_started(self):
        return self.time_watched - datetime.timedelta(seconds=self.seconds_watched)

    def time_ended(self):
        return self.time_watched

    def minutes_spent(self):
        return util.minutes_between(self.time_started(), self.time_ended())

    def key_for_video(self):
        return VideoLog.video.get_value_for_datastore(self)

    @classmethod
    def from_json(cls, json, video, user=None):
        """This method exists for testing convenience only. It's called only
        by code that runs in exclusively in development mode. Do not rely on
        this method in production code. If you need to break this code to
        implement some new feature, feel free!
        """
        user = user or users.User(json['user'])
        return cls(
            user=user,
            video=video,
            video_title=json['video_title'],
            time_watched=util.parse_iso8601(json['time_watched']),
            seconds_watched=int(json['seconds_watched']),
            last_second_watched=int(json['last_second_watched']),
            points_earned=int(json['points_earned']),
            playlist_titles=json['playlist_titles']
        )


def _set_css_deferred(user_data_key, video_key, status, version):
    user_data = user_models.UserData.get(user_data_key)
    uvc = UserVideoCss.get_for_user_data(user_data)
    css = pickle.loads(uvc.pickled_dict)

    id = '.v%d' % video_key.id()
    if status == UserVideoCss.STARTED:
        if id in css['completed']:
            logging.warn("video [%s] for [%s] went from completed->started. ignoring." %
                         (video_key, user_data_key))
        else:
            css['started'].add(id)
    else:
        css['started'].discard(id)
        css['completed'].add(id)

    uvc.pickled_dict = pickle.dumps(css, pickle.HIGHEST_PROTOCOL)
    uvc.load_pickled()

    # if set_css_deferred runs out of order then we bump the version number
    # to break the cache
    if version < uvc.version:
        version = uvc.version + 1
        user_data.uservideocss_version += 1
        db.put(user_data)

    uvc.version = version
    db.put(uvc)


class UserVideo(db.Model):
    """A single user's interaction with a single video."""
    @staticmethod
    def get_key_name(video_or_youtube_id, user_data):
        id = video_or_youtube_id
        if type(id) not in [str, unicode]:
            id = video_or_youtube_id.youtube_id
        return user_data.key_email + ":" + id

    @staticmethod
    def get_for_video_and_user_data(video, user_data, insert_if_missing=False):
        if not user_data:
            return None
        key = UserVideo.get_key_name(video, user_data)

        if insert_if_missing:
            return UserVideo.get_or_insert(
                        key_name=key,
                        user=user_data.user,
                        video=video,
                        duration=video.duration)
        else:
            return UserVideo.get_by_key_name(key)

    @staticmethod
    def count_completed_for_user_data(user_data):
        return UserVideo.get_completed_user_videos(user_data).count(limit=10000)

    @staticmethod
    def get_completed_user_videos(user_data):
        query = UserVideo.all()
        query.filter("user =", user_data.user)
        query.filter("completed =", True)
        return query

    user = db.UserProperty()
    video = db.ReferenceProperty(Video)

    # Most recently watched second in video (playhead state)
    last_second_watched = db.IntegerProperty(default=0, indexed=False)

    # Number of seconds actually spent watching this video, regardless of jumping around to various
    # scrubber positions. This value can exceed the total duration of the video if it is watched
    # many times, and it doesn't necessarily match the percent watched.
    seconds_watched = db.IntegerProperty(default=0)

    last_watched = db.DateTimeProperty(auto_now_add=True)
    duration = db.IntegerProperty(default=0, indexed=False)
    completed = db.BooleanProperty(default=False)

    @property
    def points(self):
        return points.VideoPointCalculator(self)

    @property
    def progress(self):
        if self.completed:
            return 1.0
        elif self.duration <= 0:
            logging.info("UserVideo.duration has invalid value %r, key: %s" % (self.duration, str(self.key())))
            return 0.0
        else:
            return min(1.0, float(self.seconds_watched) / self.duration)

    @classmethod
    def from_json(cls, json, user_data):
        """This method exists for testing convenience only. It's called only
        by code that runs in exclusively in development mode. Do not rely on
        this method in production code. If you need to break this code to
        implement some new feature, feel free!
        """
        readable_id = json['video']['readable_id']
        video = Video.get_for_readable_id(readable_id)

        return cls(
            key_name=UserVideo.get_key_name(video, user_data),
            user=user_data.user,
            video=video,
            last_watched=util.parse_iso8601(json['last_watched']),
            last_second_watched=int(json['last_second_watched']),
            seconds_watched=int(json['seconds_watched']),
            duration=int(json['duration']),
            completed=bool(json['completed'])
        )


class UserVideoCss(db.Model):
    """Holds data on whether to put a checkmark/circle next to video titles."""
    user = db.UserProperty()
    video_css = db.TextProperty()
    pickled_dict = db.BlobProperty()
    last_modified = db.DateTimeProperty(required=True, auto_now=True, indexed=False)
    version = db.IntegerProperty(default=0, indexed=False)

    STARTED, COMPLETED = range(2)

    @staticmethod
    def get_for_user_data(user_data):
        p = pickle.dumps({'started': set([]), 'completed': set([])}, 
                         pickle.HIGHEST_PROTOCOL)
        return UserVideoCss.get_or_insert(UserVideoCss._key_for(user_data),
                                          user=user_data.user,
                                          video_css='',
                                          pickled_dict=p,
                                          )

    @staticmethod
    def _key_for(user_data):
        return 'user_video_css_%s' % user_data.key_email

    @staticmethod
    def set_started(user_data, video, version):
        """ Enqueues a task to asynchronously update the UserVideoCss to
        indicate the user has started the video. """
        deferred.defer(_set_css_deferred, user_data.key(), video.key(),
                       UserVideoCss.STARTED, version,
                       _queue="video-log-queue",
                       _url="/_ah/queue/deferred_videolog")

    @staticmethod
    def set_completed(user_data, video, version):
        """ Enqueues a task to asynchronously update the UserVideoCss to
        indicate the user has completed the video. """
        deferred.defer(_set_css_deferred, user_data.key(), video.key(),
                       UserVideoCss.COMPLETED, version,
                       _queue="video-log-queue",
                       _url="/_ah/queue/deferred_videolog")

    @staticmethod
    def _chunker(seq, size):
        return (seq[pos:pos + size] for pos in xrange(0, len(seq), size))

    def load_pickled(self):
        max_selectors = 20
        css_list = []
        css = pickle.loads(self.pickled_dict)

        started_css = '{background-image:url(/images/video-indicator-started.png);padding-left:14px;}'
        complete_css = '{background-image:url(/images/video-indicator-complete.png);padding-left:14px;}'

        for id in UserVideoCss._chunker(list(css['started']), max_selectors):
            css_list.append(','.join(id))
            css_list.append(started_css)

        for id in UserVideoCss._chunker(list(css['completed']), max_selectors):
            css_list.append(','.join(id))
            css_list.append(complete_css)

        self.video_css = ''.join(css_list)


def _get_mangled_topic_name(topic_name):
    for char in " :()":
        topic_name = topic_name.replace(char, "")
    return topic_name

