/**
 * Views and logic for exercise/stack/card interactions
 *
 * Catalog of events triggered on Exercises:
 *
 *   * problemTemplateRendered -- when a problem template that is ready for
 *   khan-exercises targetting is rendered
 *
 *   * readyForNextProblem -- when a card is ready for the next problem to
 *   be rendered by khan-exercises
 *
 *   * upcomingExercise -- when a new exercise is approaching in the upcoming
 *   queue, this is triggered to give listeners a chance to preload any
 *   requirements
 *
 *   * warning -- when a warning about issues like disabled sessionStorage
 *   has been fired
 *
 */
var Exercises = {

    exercise: null,
    userTopic: null,

    currentCard: null,
    currentCardView: null,

    incompleteStack: null,
    incompleteStackView: null,

    completeStack: null,
    completeStackView: null,

    // Keeps track of # of pending API requests
    pendingAPIRequests: 0,

    /**
     * Called to initialize the exercise page. Passed in with JSON information
     * rendered from the server.
     */
    init: function(json) {

        this.userTopic = new Exercises.UserTopic(json.userTopic);

        this.incompleteStack = new Exercises.StackCollection(this.userTopic.get("incompleteStack")); 
        this.completeStack = new Exercises.StackCollection(this.userTopic.get("completeStack")); 

        // Start w/ the first card ready to go
        this.currentCard = this.incompleteStack.pop();

        Exercises.BottomlessQueue.init(json.userExercises);

    },

    render: function() {

        Handlebars.registerPartial("exercise-header", Templates.get("exercises.exercise-header"));
        Handlebars.registerPartial("card", Templates.get("exercises.card"));
        Handlebars.registerPartial("card-leaves", Templates.get("exercises.card-leaves"));

        var profileExercise = Templates.get("exercises.exercise");

        $(".exercises-content-container").html(profileExercise({
            // TODO(kamens): this data is faked
            name: "Topic/Exercise Name"
        }));

        this.incompleteStackView = new Exercises.StackView({
            collection: this.incompleteStack,
            el: $(".incomplete-stack"),
            frontVisible: false
        }); 

        this.completeStackView = new Exercises.StackView({
            collection: this.completeStack,
            el: $(".complete-stack"),
            frontVisible: true
        }); 

        this.currentCardView = new Exercises.CurrentCardView({
            model: this.currentCard,
            el: $(".current-card") }
        );

        this.currentCardView.render();
        this.incompleteStackView.render();
        this.completeStackView.render();

        this.bindEvents();

    },

    bindEvents: function() {

        // Triggered when Next Question has been clicked.
        //
        // Flip to the next card every time a new problem is generated by
        // khan-exercises
        //
        // TODO: eventually this event trigger should be owned by this object
        // instead of khan-exercises so we have better control of when to
        // render the results of khan-exercises or, alternatively, other
        // content inside of each card.
        $(Khan).bind("gotoNextProblem", function() {

            // Start the next card process
            Exercises.nextCard();

            // Return false so we take control of when nextProblem is triggered
            return false;

        });

        // Triggered when a problem is done (correct answer received,
        // regardless of hints/attempts) but before Next Question
        // has been clicked
        $(Khan).bind("problemDone", function() {

            // Current card is done, lock in available leaves
            Exercises.currentCard.set({
                done: true, 
                leavesEarned: Exercises.currentCard.get("leavesAvailable")
            });

        });

        // Triggered when a user attempts an answer
        $(Khan).bind("checkAnswer", function(ev, data) {

            if (data.pass === true) {

                if (data.fast === true) {
                    // Speed completion earns 4 leaves right now
                    Exercises.currentCard.decreaseLeavesAvailable(4);
                } else {
                    // Ordinary problem completion earns 3
                    Exercises.currentCard.decreaseLeavesAvailable(3);
                }

            } else if (data.pass === false) {
                // Incorrect answer drops leaves possibility to 2
                Exercises.currentCard.decreaseLeavesAvailable(2);
            }

        });

        $(Khan).bind("hintUsed", function() {
            // Using a hint drops leaves possibility to 2.
            Exercises.currentCard.decreaseLeavesAvailable(2);
        });

        $(Khan).bind("allHintsUsed", function() {
            // Using all hints drops leaves possibility to 1.
            Exercises.currentCard.decreaseLeavesAvailable(1);
        });

        $(Khan)
            .bind("apiRequestStarted", function() { Exercises.pendingAPIRequests++; })
            .bind("apiRequestEnded", function() { Exercises.pendingAPIRequests--; });

    },

    nextCard: function() {

        // animationOptions.deferreds stores all pending animations
        // that each subsequent step can wait on via $.when if needed
        var animationOptions = { deferreds: [] };

        if (this.currentCard) {

            // Move current to complete
            this.completeStack.add(this.currentCard, animationOptions);

            // Empty current card
            this.currentCard = null;

            animationOptions.deferreds.push(this.currentCardView.animateToRight());

        }

        // Wait for push-to-right animations to finish
        $.when.apply(null, animationOptions.deferreds).done(function() {

            // Detach events from old view
            Exercises.currentCardView.detachEvents();

            // Pop from left
            Exercises.currentCard = Exercises.incompleteStack.pop(animationOptions);

            // Render next card
            Exercises.currentCardView = new Exercises.CurrentCardView({
                model: Exercises.currentCard,
                el: $(".current-card") }
            );
            Exercises.currentCardView.render();

            // Finish animating from left
            $.when(Exercises.currentCardView.moveLeft()).done(function() {

                setTimeout(function() {
                    Exercises.currentCardView.animateFromLeft();
                }, 1);

            });

        });

    }

};

/**
 * Model of any (current or in-stack) card
 */
Exercises.Card = Backbone.Model.extend({

    leaves: function(card) {

        return _.map(_.range(4), function(index) {
            
            return {
                index: index,
                state: (this.get("leavesEarned") > index ? "earned" : 
                            this.get("leavesAvailable") > index ? "available" :
                                "unavailable")
            };

        }, this);

    },

    /**
     * Decreases leaves available -- if leaves available is already at this
     * level or lower, noop
     */
    decreaseLeavesAvailable: function(leavesAvailable) {

        var currentLeaves = this.get("leavesAvailable");
        if (currentLeaves) {
            leavesAvailable = Math.min(currentLeaves, leavesAvailable);
        }

        return this.set({ leavesAvailable: leavesAvailable });

    },

    /**
     * Increases leaves earned for this card -- if leaves earned is already
     * at this level or higher, noop
     */
    increaseLeavesEarned: function(leavesEarned) {

        var currentLeaves = this.get("leavesEarned");
        if (currentLeaves) {
            leavesEarned = Math.max(currentLeaves, leavesEarned);
        }

        // leavesEarned takes precedence over leavesAvailable because
        // leavesEarned is only set when the card is done, and leavesAvailable
        // no longer matters at this point.
        // 
        // We update leavesAvailable here just to keep the card's data consistent.
        return this.set({ leavesEarned: leavesEarned, leavesAvailable: leavesEarned });

    },

});

/**
 * Collection model of a stack of cards
 */
Exercises.StackCollection = Backbone.Collection.extend({

    model: Exercises.Card,

    peek: function() {
        return _.head(this.models);
    },

    pop: function(animationOptions) {
        var head = this.peek();
        this.remove(head, animationOptions);
        return head;
    },

    /**
     * Return the longest streak of cards in this stack
     * that satisfies the truth test fxn
     */
    longestStreak: function(fxn) {

        var current = 0,
            longest = 0;

        this.each(function(card) {

            if (fxn(card)) {
                current += 1;
            } else {
                current = 0;
            }

            longest = Math.max(current, longest);

        });

        return longest;

    },

    /**
     * Return a dictionary of interesting, positive stats about this stack.
     */
    stats: function() {

        var totalLeaves = this.reduce(function(sum, card) {
            return card.get("leavesEarned") + sum;
        }, 0);

        var longestStreak = this.longestStreak(function(card) {
            return card.get("leavesEarned") >= 3;
        });

        var longestSpeedStreak = this.longestStreak(function(card) {
            return card.get("leavesEarned") >= 4;
        });

        return {
            "longestStreak": longestStreak,
            "longestSpeedStreak": longestSpeedStreak,
            "totalLeaves": totalLeaves
        };
    }

});

/**
 * View of a stack of cards
 */
Exercises.StackView = Backbone.View.extend({

    template: Templates.get("exercises.stack"),

    initialize: function() {

        // deferAnimation is a wrapper function used to insert
        // any animations returned by fxn onto animationOption's
        // list of deferreds. This lets you chain complex
        // animations (see Exercises.nextCard).
        var deferAnimation = function(fxn) {
            return function(model, collection, options) {
                var result = fxn.call(this, model, collection, options);

                if (options && options.deferreds) {
                    options.deferreds.push(result);
                }

                return result;
            }
        };

        this.collection
            .bind("add", deferAnimation(function(card) {
                return this.animatePush(card);
            }), this)
            .bind("remove", deferAnimation(function() {
                return this.animatePop();
            }), this)
            .bind("change:leavesEarned", function(card) {
                this.updateSingleCard(card);
            }, this);

    },

    render: function() {

        var collectionContext = _.map(this.collection.models, function(card, index) {
            return this.viewContext(card, index);
        }, this);

        this.el.html(this.template({cards: collectionContext}));

        return this;

    },

    updateSingleCard: function(card) {

        var context = this.viewContext(card, _.indexOf(this.collection.models, card));

        $("#card-cid-" + card.cid)
            .replaceWith(
                $(Templates.get("exercises.card")(context))
            );

    },

    viewContext: function(card, index) {
        return _.extend( card.toJSON(), {
            index: index,
            frontVisible: this.options.frontVisible, 
            cid: card.cid,
            leaves: card.leaves()
        });
    },

    /**
     * Animate popping card off of stack
     */
    animatePop: function() {

        return this.el
            .find(".card-container")
                .first()
                    .slideUp(140, function() { $(this).remove(); });

    },

    /**
     * Animate pushing card onto head of stack
     */
    animatePush: function(card) {

        var context = this.viewContext(card, this.collection.length);

        return this.el
            .find(".stack")
                .prepend(
                    $(Templates.get("exercises.card")(context))
                        .css("display", "none")
                )
                .find(".card-container")
                    .first()
                        .delay(40)
                        .slideDown(140);

    }

});

/**
 * View of the single, currently-visible card
 */
Exercises.CurrentCardView = Backbone.View.extend({

    template: Templates.get("exercises.current-card"),

    model: null,

    leafEvents: ["change:done", "change:leavesEarned", "change:leavesAvailable"],

    initialize: function() {
        this.attachEvents();
    },

    attachEvents: function() {
        _.each(this.leafEvents, function(leafEvent) {
            this.model.bind(leafEvent, function() { this.updateLeaves(); }, this);
        }, this);
    },

    detachEvents: function() {
        _.each(this.leafEvents, function(leafEvent) {
            this.model.unbind(leafEvent);
        }, this);
    },

    /**
     * Renders the current card appropriately by card type.
     */
    render: function() {

        switch (this.model.get("cardType")) {

            case "problem":
                this.renderProblemCard();
                break;

            case "endofstack":
                this.renderEndOfStackCard();
                break;

            default:
                throw "Trying to render unknown card type";

        }

        return this;
    },

    viewContext: function() {
        return _.extend( this.model.toJSON(), {
            leaves: this.model.leaves()
        });
    },

    /**
     * Renders the base card's structure, including leaves
     */
    renderCardContainer: function() {
        this.el.html(this.template(this.viewContext()));
    },

    /**
     * Renders the card's type-specific contents into contents container
     */
    renderCardContents: function(templateName, optionalContext) {

        var context = _.extend({}, this.viewContext(), optionalContext);

        this.el
            .find(".current-card-contents")
                .html(
                    $(Templates.get(templateName)(context))
                );

    },

    /**
     * Renders a new card showing an exercise problem via khan-exercises
     */
    renderProblemCard: function() {

        // khan-exercises currently both generates content and hooks up
        // events to the exercise interface. This means, for now, we don't want 
        // to regenerate a brand new card when transitioning between exercise
        // problems.

        // TODO: in the future, if khan-exercises's problem generation is
        // separated from its UI events a little more, we can just rerender
        // the whole card for every problem.

        if (!$("#problemarea").length) {

            this.renderCardContainer();
            this.renderCardContents("exercises.problem-template");

            // Tell khan-exercises to setup its DOM and event listeners
            $(Exercises).trigger("problemTemplateRendered");

        }

        this.renderExerciseInProblemCard();

        // Update leaves since we may have not generated a brand new card
        this.updateLeaves();

    },

    renderExerciseInProblemCard: function() {

        var nextUserExercise = Exercises.BottomlessQueue.next();
        if (nextUserExercise) {
            // khan-exercises is listening and will fill the card w/ new problem contents
            $(Exercises).trigger("readyForNextProblem", nextUserExercise);
        }

    },

    /**
     * Renders a new card showing end-of-stack statistics
     */
    renderEndOfStackCard: function() {

        function tryRenderEndOfStackStats() {

            if (Exercises.pendingAPIRequests > 0) {

                // Wait for any outbound API requests to finish.
                setTimeout(tryRenderEndOfStackStats, 500);

            } else {

                // All API calls done and stats should be up-to-date
                // for rendering.
                Exercises.currentCardView.renderCardContents("exercises.end-of-stack", Exercises.completeStack.stats());

            }

        };

        // Start off by showing the "calculations in progress" card...
        this.renderCardContainer();
        this.renderCardContents("exercises.end-of-stack-calculating");

        // ...and wait a bit for dramatic effect before trying to show stats.
        setTimeout(tryRenderEndOfStackStats, 2000);

    },

    /**
     * Update the currently available or earned leaves in current card's view
     */
    updateLeaves: function() {
        this.el
            .find(".leaves-container")
                .html(
                    $(Templates.get("exercises.card-leaves")(this.viewContext()))
                ); 
    },

    /**
     * Animate current card to right-hand completed stack
     */
    animateToRight: function() {
        this.el.addClass("shrinkRight");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    },

    /**
     * Animate card from left-hand completed stack to current card
     */
    animateFromLeft: function() {
        this.el
            .removeClass("notransition")
            .removeClass("shrinkLeft");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    },

    /**
     * Move (unanimated) current card from right-hand stack to left-hand stack between
     * toRight/fromLeft animations
     */
    moveLeft: function() {
        this.el
            .addClass("notransition")
            .removeClass("shrinkRight")
            .addClass("shrinkLeft");

        // These animation fxns explicitly return null as they are used in deferreds
        // and may one day have deferrable animations (CSS3 animations aren't
        // deferred-friendly).
        return null;
    }

});

Exercises.UserTopic = Backbone.Model.extend({

    defaults: {
        completeStack: [],
        incompleteStack: []
    },

    initialize: function() {
        // TODO(kamens): figure out the persistance model and hook 'er up
    }

});

