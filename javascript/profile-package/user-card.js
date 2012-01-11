/**
 * Code to handle the public components of a profile.
 */

// TODO: rename UserCardModel

/**
 * Profile information about a user.
 * May be complete, partially filled, or mostly empty depending on the
 * permissions the current user has to this profile.
 */
UserCardModel = Backbone.Model.extend({
    defaults: {
        "avatarName": "darth",
        "avatarSrc": "/images/darth.png",
        "countExercisesProficient": 0,
        "countVideosCompleted": 0,
        "dateJoined": "",
        "email": "",
        "isCoachingLoggedInUser": false,
        "nickname": "",
        "points": 0,
        "username": ""
    },

    url: "/api/v1/user/profile",

    /**
     * Override Backbone.Model.save since only some of the fields are
     * mutable and saveable.
     */
    save: function(attrs, options) {
        options = options || {};
        options.contentType = "application/json";
        options.data = JSON.stringify({
            // Note that Backbone.Model.save accepts arguments to save to
            // the model before saving, so check for those first.
            "avatarName": (attrs && attrs["avatarName"]) ||
                          this.get("avatarName"),
            "nickname": (attrs && attrs["nickname"]) ||
                          this.get("nickname"),
            "username": (attrs && attrs["username"]) ||
                          this.get("username")
        });

        Backbone.Model.prototype.save.call(this, attrs, options);
    },

    /**
     * Toggle isCoachingLoggedInUser field client-side.
     * Update server-side if optional options parameter is provided.
     */
    toggleIsCoachingLoggedInUser: function(options) {
        var isCoaching = this.get("isCoachingLoggedInUser");

        this.set({"isCoachingLoggedInUser": !isCoaching});

        if (options) {
            options = $.extend({
                url: "/api/v1/user/coaches/" + this.get("email"),
                type: isCoaching ? "DELETE" : "POST",
                dataType: "json"
            }, options);

            $.ajax(options);
        }
    },

    validateUsername: function(username) {
        // Can't define validate() (or I don't understand how to)
        // because of https://github.com/documentcloud/backbone/issues/233
        username = username.toLowerCase()
                    .replace(/\./g, "");

        if (/^[a-z][a-z0-9]{4,}$/.test(username)) {
            $.ajax({
                url: "/api/v1/user/username_available",
                type: "GET",
                data: {
                    username: username
                },
                dataType: "json",
                success: _.bind(this.onValidateUsernameResponse_, this)
            });
        } else {
            var message = "";
            if (username.length < 5) {
                message = "too short";
            } else if (/^[^a-z]/.test(username)) {
                message = "must begin with a letter";
            } else {
                message = "must be alphanumeric";
            }
            this.trigger("validate:username", false, message);
        }
    },

    onValidateUsernameResponse_: function(isUsernameAvailable) {
        var message = isUsernameAvailable ? "available!!!" : "not available :(";
        this.trigger("validate:username", isUsernameAvailable, message);
    }
});

UserCardView = Backbone.View.extend({
    className: "user-info",

    events: {
        "click .avatar-pic-container": "onAvatarClick_",
        "mouseenter .avatar-pic-container": "onAvatarHover_",
        "mouseleave .avatar-pic-container": "onAvatarLeave_",
        "change #nickname": "onNicknameChanged_",
        "click .add-remove-coach": "onAddRemoveCoachClicked_",
        "click #edit-visibility": "onEditVisibilityCicked_",
        "click #edit-nickname": "onEditNicknameClicked_",
        "click #edit-username": "onEditUsernameClicked_",
        "mouseenter ul.dropdown li": "onDropdownEnter_",
        "mouseleave ul.dropdown li": "onDropdownLeave_"
     },

    initialize: function() {
        this.template = Templates.get("profile.user-card");

        this.model.bind("change:avatarSrc", _.bind(this.onAvatarChanged_, this));
        this.model.bind("change:isCoachingLoggedInUser",
                _.bind(this.onIsCoachingLoggedInUserChanged_, this));

        /**
         * The picker UI component which shows a dialog to change the avatar.
         * @type {Avatar.Picker}
         */
        this.avatarPicker_ = null;
        this.usernamePicker_=  null;

        // Modal view that contains the username and nickname pickers.
        this.modalEditView_ = null;
    },

    /**
     * Updates the source preview of the avatar. This does not affect the model.
     */
    onAvatarChanged_: function() {
        this.$("#avatar-pic").attr("src", this.model.get("avatarSrc"));
    },

    render: function() {
        var json = this.model.toJSON();
        // TODO: this data isn't specific to any profile and is more about the library.
        // It should probably be moved out eventially.
        json["countExercises"] = UserCardView.countExercises;
        json["countVideos"] = UserCardView.countVideos;
        $(this.el).html(this.template(json)).find("abbr.timeago").timeago();

        this.bindQtip_();

        return this;
    },

    bindQtip_: function() {
        // TODO: beautify me!
        this.$("#edit-visibility").qtip({
            content: {
                text: "helpful description goes here?"
            },
            style: {
                classes: "ui-tooltip-youtube"
            },
            position: {
                my: "top center",
                at: "bottom center"
            },
            hide: {
                fixed: true,
                delay: 150
            }
        });
    },

    /**
     * Handles a change to the nickname edit field in the view.
     * Propagates the change to the model.
     */
    onNicknameChanged_: function(e) {
        // TODO: validate
        var value = this.$("#nickname").val();
        this.model.save({ "nickname": value });
    },

    onAvatarHover_: function(e) {
        this.$(".avatar-change-overlay").show();
    },

    onAvatarLeave_: function(e) {
        this.$(".avatar-change-overlay").hide();
    },

    onAvatarClick_: function(e) {
        if (!this.avatarPicker_) {
            this.avatarPicker_ = new Avatar.Picker(this.model);
        }
        this.avatarPicker_.show();
    },

    onAddRemoveCoachClicked_: function(e) {
        var options = {
            success: _.bind(this.onAddRemoveCoachSuccess_, this),
            error: _.bind(this.onAddRemoveCoachError_, this)
        };

        this.model.toggleIsCoachingLoggedInUser(options);
    },

    onAddRemoveCoachSuccess_: function(data) {
        // TODO: message to user
    },

    onAddRemoveCoachError_: function(data) {
        // TODO: message to user

        // Because the add/remove action failed,
        // toggle back to original client-side state.
        this.model.toggleIsCoachingLoggedInUser();
    },

    /**
     * Toggles the display of the add/remove coach buttons.
     * Note that only one is showing at any time.
     */
    onIsCoachingLoggedInUserChanged_: function() {
        this.$(".add-remove-coach").toggle();
    },

    onDropdownEnter_: function(evt) {
        $(evt.currentTarget).addClass("hover");
    },

    onDropdownLeave_: function(evt) {
        $(evt.currentTarget).removeClass("hover");
    },

    onEditVisibilityCicked_: function() {
        // TODO: set public/private flag server side
        this.$("#edit-visibility img").toggle();
    },

    onEditNicknameClicked_: function(e) {
        e.preventDefault();
    },

    onEditUsernameClicked_: function(e) {
        e.preventDefault();

        if (!this.usernamePicker_) {
            this.usernamePicker_ = new UsernamePickerView({model: this.model});
        }

        if (!this.modalEditView_) {
            this.modalEditView_ = this.$("#edit-profile-container").modal({
                keyboard: true,
                backdrop: true
            });
        }

        this.modalEditView_.html(this.usernamePicker_.render().el)
                .modal("toggle");
    }

});

// TODO: these should probably go into some other place about the library.
/**
 * The total number of videos in the Khan Academy library.
 */
UserCardView.countVideos = 0;

/**
 * The total number of exercises in the Khan Academy library.
 */
UserCardView.countExercises = 0;
