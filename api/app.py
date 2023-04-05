import json

from os import environ
from re import fullmatch
from bson import ObjectId
from pymongo import MongoClient
from typing import Union, Optional
from dotenv import load_dotenv, find_dotenv
from werkzeug.security import generate_password_hash
from werkzeug.wrappers import Response as RedirectResponse
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    Response as FlaskResponse,
)
from helpers import (
    login_required,
    isValidLogin,
    query,
    getArticle,
    saveArticle,
    searchPost,
    uploadImage,
    getDbTable,
    getArticleId,
    getProfileInfo,
    destructureProfileImgs,
)

load_dotenv(find_dotenv())
app: Flask = Flask(__name__)
app.secret_key = environ.get("SECRET_KEY")

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Configure upload settings
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Type aliases
SearchPostResponse = Union[RedirectResponse, None]


# Ensure responses aren't cached
@app.after_request
def after_request(response: FlaskResponse) -> FlaskResponse:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/", methods=["GET", "POST"])
def index() -> Union[SearchPostResponse, str]:
    if request.method == "POST":
        return searchPost()

    return render_template("index.html", index=True, loggedInId=session.get("user_id"))


@app.route("/articles", methods=["GET", "POST"])
def searchArticles() -> Union[SearchPostResponse, str]:
    if request.method == "POST":
        return searchPost()

    # Handle empty state if there is no query param on the URL
    search: str | None = request.args.get("q")

    if not search:
        return render_template("search.html", emptyState=True)

    response: dict = query(search)
    return render_template("search.html", response=response)


@app.route("/articles/<articleURL>", methods=["GET", "POST"])
def articleId(articleURL):
    # Connect to MongoDB and retrieve the username
    connection = MongoClient(environ.get("MONGODB_URI"))
    savedArticlesTable = getDbTable(connection, "savedArticles")

    articleId = getArticleId(articleURL)
    article = getArticle(savedArticlesTable, articleId)

    # Handle POST method if the user search someting on the search bar
    if request.method == "POST":
        search = request.form.get("search")

        if search:
            return searchPost()

        loggedInId = ObjectId(session.get("user_id"))

        if loggedInId:
            saveArticle(savedArticlesTable, articleId, loggedInId)
        else:
            return redirect("/login")

    connection.close()
    return render_template("article.html", article=article)


# RegExs to validate inputs
userRegEx = "[A-Za-z0-9._-]{3,16}"
emailRegEx = "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"
passwordRegEx = "[A-Za-z0-9¡!¿?$+._-]{6,16}"


@app.route("/signup", methods=["GET", "POST"])
def signup():
    # Forget any user_id
    session.clear()

    if request.method == "POST":
        search = request.form.get("search")

        if search:
            return redirect(f"/articles?q={search}")

        username = request.form.get("username")
        email = request.form.get("email").lower()
        password = request.form.get("password")
        confirmedPassword = request.form.get("confirmed-password")

        # Check if username is valid or not
        if not fullmatch(userRegEx, username):
            if len(username) < 3 or len(username) > 16:
                errorMessage = "Username must be at least 3 characters, with a maximum of 16 characters."
                return render_template("signup.html", errorMessage=errorMessage)

            errorMessage = "Invalid username. Please, use valid special characters (underscore, minus, and periods)."
            return render_template("signup.html", errorMessage=errorMessage)

        elif len(email) < 6 or len(email) > 64:
            errorMessage = (
                "Email must be at least 6 characters, with a maximum of 64 characters."
            )
            return render_template("signup.html", errorMessage=errorMessage)

        # Check if email is valid or not
        elif not fullmatch(emailRegEx, email):
            errorMessage = "Invalid email. Please, try again."
            return render_template("signup.html", errorMessage=errorMessage)

        elif password != confirmedPassword:
            errorMessage = (
                "Password and confirmation does not match. Please, try again."
            )
            return render_template("signup.html", errorMessage=errorMessage)

        # Check if password is valid or not
        elif not fullmatch(passwordRegEx, password):
            if len(password) < 6 or len(password) > 16:
                errorMessage = "Password must be at least 6 characters, with a maximum of 16 characters."
                return render_template("signup.html", errorMessage=errorMessage)

            errorMessage = "Invalid password. Please, use valid special characters."
            return render_template("signup.html", errorMessage=errorMessage)

        # Check both if username or password have two or more consecutive periods
        elif ".." in username or ".." in password:
            errorMessage = "Username and password cannot contain two or more consecutive periods (.)."
            return render_template("signup.html", errorMessage=errorMessage)

        # Check both if username and/or password already exists. If not, then the account
        # is created
        else:
            connection = MongoClient(environ.get("MONGODB_URI"))
            usersTable = getDbTable(connection, "users")

            errorMessage = "The username is already taken. Please, try again or "
            exists = usersTable.find_one(
                {"username": username}, {"username": 1, "_id": 0}
            )

            if exists:
                return render_template("signup.html", errorMessage=errorMessage)

            exists = usersTable.find_one({"email": email}, {"email": 1, "_id": 0})

            if exists:
                errorMessage = errorMessage.replace("username", "email")
                return render_template("signup.html", errorMessage=errorMessage)

            hashedPassword = generate_password_hash(
                password, method="pbkdf2:sha256", salt_length=8
            )

            # If everything is correct and has passed all the conditions, then we create
            # the user object that we want to insert on the database, and insert it
            userToInsert = {
                "username": username,
                "email": email,
                "hash": hashedPassword,
            }
            usersTable.insert_one(userToInsert)
            userId = usersTable.find_one({"username": username}, {"_id": 1})["_id"]
            session["user_id"] = str(userId)
            connection.close()

            return redirect("/")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    # Clear session cookies
    session.clear()

    if request.method == "POST":
        search = request.form.get("search")

        if search:
            return redirect(f"/articles?q={search}")

        user = request.form.get("user").lower()
        password = request.form.get("password")
        regExs = {
            "username": userRegEx,
            "email": emailRegEx,
            "password": passwordRegEx,
        }

        response = isValidLogin(user, password, regExs, session)

        if response["isValidLogin"] == False:
            # This code from here modifies the error message depending whether the user
            # has tried to log in with either his username or his email
            errorMessage = (
                "Your username and/or password are incorrect. Please, try again."
            )
            if response["usernameOrEmail"] == "email":
                errorMessage = errorMessage.replace("username", "email")

            return render_template("login.html", errorMessage=errorMessage)
        else:
            return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    # Clear session cookies
    session.clear()
    return redirect("/")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    connection = MongoClient(environ.get("MONGODB_URI"))
    usersTable = getDbTable(connection, "users")
    loggedInId = ObjectId(session.get("user_id"))

    if request.method == "POST":
        search = request.form.get("search")

        if search:
            return redirect(f"/articles?q={search}")

        profilePic = request.files["profilePic"]
        bannerPic = request.files["bannerPic"]

        if profilePic or bannerPic:
            username = usersTable.find_one(
                {"_id": loggedInId}, {"username": 1, "_id": 0}
            )["username"]
            return uploadImage(profilePic, bannerPic, username, connection, loggedInId)

    profileInfo = getProfileInfo(connection, loggedInId)
    connection.close()

    profileImages = profileInfo["profileImages"]
    savedArticles = profileInfo["savedArticles"]
    profilePic, bannerPic = destructureProfileImgs(profileImages)

    return render_template(
        "profile.html",
        profilePic=profilePic,
        bannerPic=bannerPic,
        savedArticles=savedArticles,
    )
