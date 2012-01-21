/**
 * Code to handle badge-related UI components.
 */

// TODO: stop clobering the stuff in pageutil.js
var Badges = window.Badges || {};

/**
 * @enum {number}
 */
Badges.ContextType = {
    NONE: 0,
    EXERCISE: 1,
    PLAYLIST: 2
};

/**
 * @enum {number}
 */
Badges.Category = {
    BRONZE: 0, // Meteorite, "Common"
    SILVER: 1, // Moon, "Uncommon"
    GOLD: 2, // Earth, "Rare"
    PLATINUM: 3, // Sun, "Epic"
    DIAMOND: 4, // Black Hole, "Legendary"
    MASTER: 5 // Summative/Academic Achievement
};

/**
 * A single badge that a user can earn.
 * Parallel to the JSON serialized formats of badges.Badge
 */
Badges.Badge = Backbone.Model.extend({
    defaults: {
        "badgeCategory": Badges.Category.BRONZE,
        "name": "__empty__",
        "description": "",
        "iconSrc": "",
        "isOwned": false,
        "points": 0,
        "safeExtendedDescription": ""
    },

    isEmpty: function() {
        // Specially reserved name for empty badge slots.
        // Used in display case - must be synced with what the server
        // understands in util_badges.py
        return this.get("name") === "__empty__";
    },

    toJSON: function() {
        var json = Badges.Badge.__super__.toJSON.call(this);
        json["isEmpty"] = this.isEmpty();
        return json;
    }
});

/**
 * A re-usable instance of an empty badge.
 */
Badges.Badge.EMPTY_BADGE = new Badges.Badge({});

/**
 * Badge information about a badge, or a set of badges that a user has earned
 * grouped by their badge type.
 * Parallel to the JSON serialized formats of badges.GroupedUserBadge
 */
Badges.UserBadge = Backbone.Model.extend({
    defaults: {
        "badge": null,
        "count": 1,
        "lastEarnedDate": "2011-11-22T00:00:00Z",
        "targetContextNames": [],
        "isOwned": true
    },

    initialize: function(attributes, options) {
        if (!this.get("badge")) {
            throw "A UserBadge object needs a reference badge object";
        }

        // Wrap the underlying badge info in a Model object and forward
        // change events.
        var badgeModel = new Badges.Badge(this.get("badge"));
        this.set({ "badge": badgeModel }, { "silent": true });
        badgeModel.bind(
            "change",
            function(ev) { this.trigger("change:badge"); },
            this);
    }
});

/**
 * A list of badges that can be listened to.
 * This list can be edited by adding or removing from the collection,
 * and saved up to a server.
 */
Badges.BadgeList = Backbone.Collection.extend({
    model: Badges.Badge,

    saveUrl: null,

    /**
     * Whether or not this badge list has been modified since the last
     * save to the server.
     */
    dirty_: false,

    setSaveUrl: function(url) {
        this.saveUrl = url;
    },

    toJSON: function() {
        return this.map(function(badge) {
            return badge.get("name");
        });
    },

    add: function(models, options) {
        Badges.BadgeList.__super__.add.apply(this, arguments);
        this.dirty_ = true;
    },

    remove: function(models, options) {
        Badges.BadgeList.__super__.remove.apply(this, arguments);
        this.dirty_ = true;
    },

    /**
     * Saves the collection to the server via Backbone.sync.
     * This does *not* save any individual edits to Badges within this list;
     * it simply posts the information about what belongs in the set.
     * @param {Object} options Options similar to what Backbone.sync accepts.
     */
    save: function(options) {
        if (!this.dirty_) {
            return;
        }
        options = options || {};
        options["url"] = this.saveUrl;
        options["contentType"] = "application/json";
        options["data"] = JSON.stringify(this.map(function(badge) {
            return badge.get("name");
        }));
        Backbone.sync.call(this, "update", this, options);
        this.dirty_ = false;
    }
});

/**
 * A list of user badges that can be listened to.
 */
Badges.UserBadgeList = Backbone.Collection.extend({
    model: Badges.UserBadge
});

/**
 * A UI component that displays a list of badges to show off.
 * Typically used in a public profile page, but can be re-used
 * in the context of a hovercard, or any other context.
 *
 * Expects a Badges.BadgeList model to back it.
 */
Badges.DisplayCase = Backbone.View.extend({
    className: "badge-display-case",

    /**
     * Whether or not this is currently in edit mode.
     */
    editing: false,

    /**
     * The full user badge list available to pick from when in edit mode.
     * @type {Badges.UserBadgeList}
     */
    fullBadgeList: null,

    /**
     * The number of slots available in the display case.
     */
    maxVisible: 5,

    /**
     * The slot number being edited. Any selection from the badge picker
     * will replace the badge in this slot number.
     * -1 if not currently editing.
     */
    selectedIndex: -1,

    mainCaseEl: null,
    badgePickerEl: null,
    editControlEl: null,

    initialize: function() {
        this.model.bind("add", this.render, this);
        this.model.bind("remove", this.render, this);
        this.model.bind("change", this.render, this);
        this.template = Templates.get("profile.badge-display-case");

        // TODO: register in some central intializing point?
        Handlebars.registerPartial(
            "badge-compact",
            Templates.get("profile.badge-compact")
        );
    },

    events: {
        "click .main-case .achievement-badge .delete-icon": "onDeleteBadgeClicked_",
        "click .main-case .achievement-badge": "onBadgeClicked_",
        "click .badge-picker .achievement-badge": "onBadgeInPickerClicked_"
    },

    /**
     * @return {boolean} Whether or not this display case can go into "edit" mode
     *        to allow a user to select which badges go inside.
     */
    isEditable: function() {
        return !!this.fullBadgeList;
    },

    /**
     * Sets the full badge list for the display case so it can go into edit
     * mode and pick badges from this badge list.
     * @param {Badges.UserBadgeList} The full list of badges that can be added
     *        to this display case.
     * @return {Badges.DisplayCase} This same instance so calls can be chained.
     */
    setFullBadgeList: function(fullBadgeList) {
        // TODO: do we want to listen to events on the full badge list?
        this.fullBadgeList = fullBadgeList;
        $(this.editControlEl).toggleClass("editable", this.isEditable());
    },

    /**
     * Enters "edit mode" where badges can be added/removed, if possible.
     * @param {number=} index Optional index of the slot in the display-case
     *        to be edited. Defaults to the first available slot, or if none
     *        are available, the last used slot.
     * @return {Badges.DisplayCase} This same instance so calls can be chained.
     */
    edit: function(index) {
        if (!this.isEditable() || this.editing) {
            return this;
        }

        this.setEditing_(true);

        this.updateEditSelection_(index);

        this.showBadgePicker_();
        this.editControlEl.slideUp(350);
        $(document).bind("click", this.getBoundStopEditFn_());
        return this;
    },

    /**
     * Updates the editor so that the badge at the specified index is
     * being edited. If no index is specified, the last possible spot
     * is selected by default.
     * @param {number=} index Optional index of the slot in the display-case
     *        to be edited. -1 to indicate that none should be selected (i.e.
     *        we're exiting edit mode.
     */
    updateEditSelection_: function(index) {
        // By default, select the first empty slot, or the last non-empty
        // slot if completely full.
        if (index === undefined) {
            for (var i = 0, len = this.model.length; i < len; i++) {
                if (this.model.at(i).isEmpty()) {
                    index = i;
                    break;
                }
            }
        }
        index = (index === undefined) ? this.model.length : index;
        var max = Math.min(this.model.length, this.maxVisible - 1);
        this.selectedIndex = Math.min(index, max);
        this.updateSelectionHighlight();
    },

    /**
     * Shows the badge picker for edit mode, if not already visible.
     * This view must have already have been rendered once.
     */
    showBadgePicker_: function() {
        this.renderBadgePicker();
        var jel = $(this.el);
        var jelPicker = $(this.badgePickerEl);
        jelPicker.slideDown("fast", function() { jelPicker.show(); })
            .css("margin-left", "300px")
            .animate({ "margin-left": "0" }, {
                duration: "fast",
                step: $.easing.easeInOutCubic,
                complete: function() {
                    jel.addClass("editing");
                }
            });

        return this;
    },

    /**
     * Handles a click to a badge in the main display case.
     */
    onBadgeClicked_: function(e) {
        if (!this.editing) {
            // Noop when not editing.
            return;
        }

        var index = $(this.mainCaseEl)
                .find(".achievement-badge")
                .index(e.currentTarget);
        this.updateEditSelection_(index);
        e.stopPropagation();
    },

    /**
     * Handles a click to a delete button for a badge in the main display case.
     */
    onDeleteBadgeClicked_: function(e) {
        // Prevent the badge click from being processed, since
        // the X is a child of the badge.
        e.stopPropagation();

        if (!this.editing) {
            // Noop when not editing.
            return;
        }

        var badgeNode = e.currentTarget;
        while (badgeNode && !$(badgeNode).hasClass("achievement-badge")) {
            badgeNode = badgeNode.parentNode;
        }
        var index = $(this.mainCaseEl)
                .find(".achievement-badge")
                .index(badgeNode);

        var isLast = index == (this.model.length - 1);
        this.model.remove(this.model.at(index));

        if (!isLast) {
            // Insert an empty badge, since we don't want things shifting
            this.model.add(Badges.Badge.EMPTY_BADGE, { at: index });
        }
        this.updateEditSelection_(index);
    },

    /**
     * Handles a click to a badge in the badge picker in edit mode.
     */
    onBadgeInPickerClicked_: function(e) {
        e.stopPropagation();

        if ($(e.currentTarget).hasClass("used")) {
            // Ignore badges already in the main case.
            return;
        }

        var name = e.currentTarget.id;
        var matchedBadge = _.find(
                this.fullBadgeList.models,
                function(userBadge) {
                    return userBadge.get("badge").get("name") == name;
                });
        if (!matchedBadge) {
            // Shouldn't happen!
            return;
        }

        // Backbone.Collection doesn't have a .replace method - do it ourselves
        // TODO: should we be cloning?
        var existing = this.model.at(this.selectedIndex);
        if (existing) {
            this.model.remove(existing);
        }
        this.model.add(
                matchedBadge.get("badge").clone(),
                { at: this.selectedIndex });

        // Pick the next empty slot.
        this.updateEditSelection_();
    },

    /**
     * Exits edit mode.
     */
    stopEdit: function() {
        if (this.editing) {
            this.setEditing_(false);
            this.updateEditSelection_(-1);
            var jelRootEl = $(this.el);
            var jelPicker = $(this.badgePickerEl);
            jelPicker.slideUp("fast", function() {
                jelRootEl.removeClass("editing");
            });
            jelPicker.undelegate();
            this.editControlEl.slideDown(250);
            $(document).unbind("click", this.getBoundStopEditFn_());

            // TODO: avoid saving if not dirty.
            this.save();
        }
        return this;
    },

    getBoundStopEditFn_: function() {
        if (this.boundStopEditFn_) {
            return this.boundStopEditFn_;
        }
        var self = this;
        return this.boundStopEditFn_ = function(e) {
            for (var node = e.target; node; node = node.parentNode) {
                if (node === self.el) {
                    // Click inside the display-case somewhere - ignore.
                    return;
                }
            }
            self.stopEdit();
        };
    },

    save: function() {
        this.model.save();
    },

    setEditing_: function(editing) {
        this.editing = editing;
    },

    /**
     * Builds a context object to render a single badge.
     */
    getUserBadgeJsonContext_: function(badge) {
        var json = badge.get("badge").toJSON();
        json["count"] = badge.get("count");
        return json;
    },

    /**
     * Gets the handlebars template context for the main display-case element.
     */
    getTemplateContext_: function() {
        var i,
            badges = [],
            numRendered = Math.min(this.maxVisible, this.model.length);
        for (i = 0; i < numRendered; i++) {
            var badge = this.model.at(i);
            badges.push(badge.toJSON());
        }
        for (; i < this.maxVisible; i++) {
            badges.push(Badges.Badge.EMPTY_BADGE.toJSON());
        }
        return { badges: badges };
    },

    /**
     * Updates the appropriate badge being highlighted for edit mode.
     * See {@link #selectedIndex} for more details.
     */
    updateSelectionHighlight: function() {
        var badgeSlots = $(".achievement-badge", this.mainCaseEl);
        badgeSlots.removeClass("selected");
        if (this.selectedIndex > -1) {
            $(badgeSlots[this.selectedIndex]).addClass("selected");
        }
    },

    onCoverClicked_: function(e) {
        if (this.isEditable()) {
            this.edit();
        }
        e.stopPropagation();
    },

    /**
     * Renders the contents of the badge picker.
     * Idempotent - simply blows away and repopulates the contents if called
     * multiple times.
     */
    renderBadgePicker: function() {
        if (this.fullBadgeList.isEmpty()) {
            $(this.badgePickerEl).html(
                    Templates.get("profile.empty-badge-picker")());
            return;
        }

        var html = [],
            badgeTemplate = Templates.get("profile.badge-compact");
        this.fullBadgeList.each(function(userBadge) {
            var alreadyInCase = this.model.find(function(b) {
                return b.get("name") === userBadge.get("badge").get("name");
            });

            // Mark badges that are already used in the display case
            var jsonContext = this.getUserBadgeJsonContext_(userBadge);
            if (alreadyInCase) {
                jsonContext["used"] = true;
            }
            html.push(badgeTemplate(jsonContext));
        }, this);
        $(this.badgePickerEl).html(html.join(""));
    },

    render: function() {
        if (!this.mainCaseEl) {
            // First render - build the chrome.
            this.mainCaseEl = $("<div class=\"main-case\"></div>");
            this.badgePickerEl =
                $("<div class=\"badge-picker fancy-scrollbar\"></div>");
            $(this.el)
                .append(this.mainCaseEl)
                .append(this.badgePickerEl);
            this.editControlEl = $(".display-case-cover");
            this.editControlEl.click(_.bind(this.onCoverClicked_, this));
            $(this.editControlEl).toggleClass("editable", this.isEditable());
        }
        $(this.mainCaseEl).html(this.template(this.getTemplateContext_()));
        if (this.fullBadgeList) {
            this.renderBadgePicker();
        }
        this.updateSelectionHighlight();
        return this;
    }
});
