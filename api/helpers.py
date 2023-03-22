import pyrebase
import requests

from PIL import Image
from re import fullmatch
from bson import ObjectId
from functools import wraps
from webptools import cwebp
from typing import TypedDict
from pymongo import MongoClient
from os import environ, path, remove
from werkzeug.utils import secure_filename
from dotenv import load_dotenv, find_dotenv
from werkzeug.security import check_password_hash
from flask import redirect, render_template, request, session

load_dotenv(find_dotenv())
apiKey: str = environ.get("API_KEY")


def searchPost():
    query: str | None = request.form.get("search")
    return redirect(f"/articles?q={query}")


# Decorate routes to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def getDBTable(connection, table: str):
    db = connection["wikifood"]
    table = db[table]
    return table


def getUsername(usersTable, logIn):
    username = usersTable.find_one({"_id": logIn}, {"username": 1, "_id": 0})[
        "username"
    ]

    return username


# Smartly recognizes whether the user has tried to log in with either his username or his
# email, and validates the login
def isValidLogin(user, password, regExs, session):
    usernameOrEmail: str | None = None

    # Before consulting anything, it first checks whether the username or email have the
    # correct syntax or not
    if fullmatch(regExs["username"], user) and len(user) >= 2 and len(user) <= 16:
        usernameOrEmail = "username"
    elif fullmatch(regExs["email"], user) and len(user) >= 2 and len(user) <= 64:
        usernameOrEmail = "email"
    else:
        return {"isValidLogin": False, "usernameOrEmail": "username"}

    invalidResponse = {"isValidLogin": False, "usernameOrEmail": usernameOrEmail}

    # Again, before consulting anything, the code first checks whether the password have
    # the correct syntax or not
    if fullmatch(regExs["password"], password):
        # Now that we know that the syntax for both username/email and password are
        # valid, we first consult with the database to find out whether the user exists
        # or not
        connection = MongoClient(environ.get("MONGODB_URI"))
        usersTable = getDBTable(connection, "users")
        userExists = usersTable.find_one({f"{usernameOrEmail}": user}, {"hash": 1})

        # If it exists, we compare the password that the user provided with the hashed
        # password stored in the database
        if userExists:
            hashedPassword: str = userExists["hash"]
            isValidPassword: bool = check_password_hash(hashedPassword, password)

            # If the password that the user provided it's the same as the hashed password
            # that we have stored in the database, then we log in the user, and return a
            # valid response
            if isValidPassword:
                userId: str = str(userExists["_id"])
                session["user_id"] = userId
                connection.close()

                response = {"isValidLogin": True}
                return response

            # If any of previous checks fails, then we return an invalid response
            else:
                return invalidResponse
        else:
            return invalidResponse
    else:
        return invalidResponse


apiDomain = "https://api.spoonacular.com"


# Make queries to search at the API
def query(search: str):
    url = f"{apiDomain}/recipes/complexSearch?apiKey={apiKey}&query={search}&number=25&addRecipeInformation=true"
    response = requests.get(url).json()

    return response


# Make queries to get information of the API
def getArticle(savedArticlesTable, articleId):
    url = f"{apiDomain}/recipes/{articleId}/information?apiKey={apiKey}"
    response = requests.get(url).json()
    logIn = session.get("user_id")

    savedArticle = savedArticlesTable.find(
        {"articleId": articleId, "userId": logIn}, {"_id": 0, "articleType": 1}
    )
    getArticle = [response, savedArticle, articleId]
    return getArticle


def saveArticle(savedArticlesTable, articleId, logIn):
    savedArticle = request.form.get("savedArticle")

    if savedArticle == "True":
        articleToDelete = {"userId": logIn, "articleId": articleId}
        savedArticlesTable.delete_one(articleToDelete)

        # table.execute(
        #     f"DELETE FROM savedArticles WHERE userId = '{logIn}' AND articleId = '{articleId}'")
        # db.commit()
    else:
        articleToInsert = {"userId": logIn, "articleId": articleId}
        savedArticlesTable.insert_one(articleToInsert)

        # table.execute(
        #     f"INSERT INTO savedArticles (userId, articleType, articleId) VALUES ('{logIn}', '{articleType}', '{articleId}')")
        # db.commit()


# Check if an image has a valid format
def allowedImage(image):
    allowedExtensions = set(["png", "jpg", "jpeg", "bmp", "webp"])
    return "." in image and image.rsplit(".", 1)[1].lower() in allowedExtensions


# Crops profile images to an 1:1 aspect ratio
def cropImage(image):
    width, height = image.size

    if width == height:
        return image

    offset = int(abs(height - width) / 2)

    if width > height:
        image = image.crop([offset, 0, width - offset, height])
    else:
        image = image.crop([0, offset, width, height - offset])
    return image


def getProfileInfo(connection, logIn):
    usersTable = getDBTable(connection, "users")
    savedArticlesTable = getDBTable(connection, "savedArticles")
    logIn = ObjectId(logIn)

    profileImages = usersTable.find_one(
        {"_id": logIn}, {"profilePic": 1, "bannerPic": 1, "_id": 0}
    )
    savedArticles = list(
        savedArticlesTable.find({"userId": logIn}, {"articleId": 1, "_id": 0})
    )

    profileInfo = {"profileImages": profileImages, "savedArticles": savedArticles}
    return profileInfo


class ProfileImages(TypedDict):
    profilePic: str
    bannerPic: str


def destructureProfileImgs(profileImages: ProfileImages) -> tuple[str, str]:
    profilePic = None
    bannerPic = None
    if "profilePic" in profileImages:
        profilePic = profileImages["profilePic"]
    if "bannerPic" in profileImages:
        bannerPic = profileImages["bannerPic"]

    return (profilePic, bannerPic)


# Saves images (banner and profile pictures), keeps a record of the images of each image of each user,
# and updates the uploaded images
def uploadImage(profilePic, bannerPic, username, connection, logIn):
    config = {
        "apiKey": environ.get("FIREBASE_API_KEY"),
        "authDomain": environ.get("AUTH_DOMAIN"),
        "projectId": environ.get("PROJECT_ID"),
        "storageBucket": environ.get("STORAGE_BUCKET"),
        "messagingSenderId": environ.get("MESSAGING_SENDER_ID"),
        "appId": environ.get("APP_ID"),
        "measurementId": environ.get("MEASUREMENT_ID"),
        "serviceAccount": {
            "type": environ.get("TYPE"),
            "project_id": environ.get("PROJECT_ID"),
            "private_key_id": environ.get("PRIVATE_KEY_ID"),
            "private_key": environ.get("PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": environ.get("CLIENT_EMAIL"),
            "client_id": environ.get("CLIENT_ID"),
            "auth_uri": environ.get("AUTH_URI"),
            "token_uri": environ.get("TOKEN_URI"),
            "auth_provider_x509_cert_url": environ.get("AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": environ.get("CLIENT_X509_CERT_URL"),
        },
        "databaseURL": environ.get("DATABASE_URL"),
    }

    firebase = pyrebase.initialize_app(config)
    storage = firebase.storage()
    profilePicDirectory = "static/temp/profilePics/"
    bannerPicDirectory = "static/temp/bannerPics/"
    usersTable = getDBTable(connection, "users")

    successfulMessage = "The image has been uploaded successfully!"
    errorMessage = "Allowed image types are: png, jpg, jpeg, webp, and bmp."

    if profilePic and bannerPic:
        if allowedImage(profilePic.filename) and allowedImage(bannerPic.filename):
            profFilename = secure_filename(profilePic.filename)
            bannFilename = secure_filename(bannerPic.filename)

            image = Image.open(profilePic)
            profilePic = cropImage(image)

            profilePic.save(path.join(profilePicDirectory, profFilename))
            bannerPic.save(path.join(bannerPicDirectory, bannFilename))

            formatIndex = profFilename.find(
                ".", len(profFilename) - 5, len(profFilename) - 1
            )
            profFilenameWebp = profFilename[:formatIndex] + ".webp"
            formatIndex = bannFilename.find(
                ".", len(bannFilename) - 5, len(bannFilename) - 1
            )
            bannFilenameWebp = bannFilename[:formatIndex] + ".webp"

            cwebp(
                input_image=profilePicDirectory + profFilename,
                output_image=profilePicDirectory + profFilenameWebp,
                option="-q 80",
            )
            cwebp(
                input_image=bannerPicDirectory + bannFilename,
                output_image=bannerPicDirectory + bannFilenameWebp,
                option="-q 80",
            )

            storage.child(profFilenameWebp).put(profilePicDirectory + profFilenameWebp)
            storage.child(bannFilenameWebp).put(bannerPicDirectory + bannFilenameWebp)

            updatedValue = {
                "profilePic": profFilenameWebp,
                "bannerPic": bannFilenameWebp,
            }
            usersTable.update_one({"username": username}, {"$set": updatedValue}, True)

            remove(profilePicDirectory + profFilename)
            remove(profilePicDirectory + profFilenameWebp)
            remove(bannerPicDirectory + bannFilename)
            remove(bannerPicDirectory + bannFilenameWebp)

            profileInfo = getProfileInfo(connection, logIn)
            connection.close()

            savedArticles = profileInfo["savedArticles"]
            profileImages = profileInfo["profileImages"]
            profilePic, bannerPic = destructureProfileImgs(profileImages)

            return render_template(
                "profile.html",
                successfulMessage=successfulMessage,
                profilePic=profilePic,
                bannerPic=bannerPic,
                username=username,
                savedArticles=savedArticles,
            )

        else:
            return render_template(
                "profile.html",
                errorMessage=errorMessage,
                username=username,
            )

    elif profilePic:
        if allowedImage(profilePic.filename):
            profFilename = secure_filename(profilePic.filename)

            image = Image.open(profilePic)
            profilePic = cropImage(image)
            profilePic.save(path.join(profilePicDirectory, profFilename))

            formatIndex = profFilename.find(
                ".", len(profFilename) - 5, len(profFilename) - 1
            )
            profFilenameWebp = profFilename[:formatIndex] + ".webp"

            cwebp(
                input_image=profilePicDirectory + profFilename,
                output_image=profilePicDirectory + profFilenameWebp,
                option="-q 80",
            )
            storage.child(profFilenameWebp).put(profilePicDirectory + profFilenameWebp)

            usersTable.update_one(
                {"username": username},
                {"$set": {"profilePic": profFilenameWebp}},
                True,
            )

            remove(profilePicDirectory + profFilename)
            remove(profilePicDirectory + profFilenameWebp)

            profileInfo = getProfileInfo(connection, logIn)
            connection.close()

            savedArticles = profileInfo["savedArticles"]
            profileImages = profileInfo["profileImages"]
            profilePic, bannerPic = destructureProfileImgs(profileImages)

            return render_template(
                "profile.html",
                successfulMessage=successfulMessage,
                profilePic=profilePic,
                bannerPic=bannerPic,
                username=username,
                savedArticles=savedArticles,
            )

        else:
            return render_template(
                "profile.html",
                errorMessage=errorMessage,
                username=username,
            )

    else:
        if allowedImage(bannerPic.filename):
            bannFilename = secure_filename(bannerPic.filename)
            bannerPic.save(path.join(bannerPicDirectory, bannFilename))

            formatIndex = bannFilename.find(
                ".", len(bannFilename) - 5, len(bannFilename) - 1
            )
            bannFilenameWebp = bannFilename[:formatIndex] + ".webp"

            cwebp(
                input_image=bannerPicDirectory + bannFilename,
                output_image=bannerPicDirectory + bannFilenameWebp,
                option="-q 80",
            )
            storage.child(bannFilenameWebp).put(bannerPicDirectory + bannFilenameWebp)

            usersTable.update_one(
                {"username": username}, {"$set": {"bannerPic": bannFilenameWebp}}
            )

            remove(bannerPicDirectory + bannFilename)
            remove(bannerPicDirectory + bannFilenameWebp)

            profileInfo = getProfileInfo(connection, logIn)
            connection.close()

            savedArticles = profileInfo["savedArticles"]
            profileImages = profileInfo["profileImages"]
            profilePic, bannerPic = destructureProfileImgs(profileImages)

            return render_template(
                "profile.html",
                successfulMessage=successfulMessage,
                profilePic=profilePic,
                bannerPic=bannerPic,
                username=username,
                savedArticles=savedArticles,
            )

        else:
            return render_template(
                "profile.html",
                errorMessage=errorMessage,
                username=username,
            )


# With this loop we can extract the article ID from the URL. Example:
# URL: 'https://.../articles/pizza-bites-with-pumpkin-19234984'
# Article ID extracted: 19234984
def getArticleId(articleURL):
    startPoint = 0
    for i in range(len(articleURL) - 1, -1, -1):
        if articleURL[i] == "-":
            startPoint = i + 1
            break

    articleId = articleURL[startPoint:]
    return articleId
