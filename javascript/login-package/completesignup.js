/**
 * Logic to deal with with step 2 of the signup process, asking the user
 * for additional information like password and username (after
 * having verified her e-mail address already).
 */

/**
 * Initializes the form for completing the signup process
 */
Login.initCompleteSignupPage = function() {
    $("#nickname").focus();

    $("#password").on("keypress", function(e) {
        if (e.keyCode === $.ui.keyCode.ENTER) {
            e.preventDefault();
            Login.submitCompleteSignup();
        }
    });

    $("#submit-button").click(function(e) {
        e.preventDefault();
        Login.submitCompleteSignup();
    });
};

/**
 * Submits the complete signup attempt if it passes pre-checks.
 */
Login.submitCompleteSignup = function() {
    var valid = Login.ensureValid_("#nickname", "Name required");
    valid = Login.ensureValid_("#username", "Username required") && valid;
    valid = Login.ensureValid_("#password", "Password required") && valid;
    if (valid) {
        Login.disableSubmitButton_();
        Login.asyncFormPost(
                $("#signup-form"),
                function(data) {
                    // 200 success, but the signup may have failed.
                    if (data["errors"]) {
                        Login.onCompleteSignupError(data["errors"]);
                        Login.enableSubmitButton_();
                    } else {
                        Login.onCompleteSignupSucess(data);
                    }
                },
                function(data) {
                    // Hard fail - can't seem to talk to server right now.
                    // TODO(benkomalo): handle.
                    Login.enableSubmitButton_();
                });
    }
};

/**
 * Handles a success response to the POST to complete the signup.
 * This will cause the page to refresh and to set the auth cookie.
 */
Login.onCompleteSignupSucess = function(data) {
    Login.onPasswordLoginSuccess(data);
};

/**
 * Handles an error from the server on an attempt to complete
 * the signup - there was probably invalid data in the forms.
 */
Login.onCompleteSignupError = function(errors) {
    var firstFailed;
    _.each(errors, function(error, fieldName) {
        $("#" + fieldName + "-error").text(error);
        if (firstFailed === undefined) {
            firstFailed = fieldName;
        }
    });
    if (firstFailed) {
        $("#" + firstFailed).focus();
    }
};

