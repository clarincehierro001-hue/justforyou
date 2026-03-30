from datetime import datetime, timezone
import os

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy import JSON

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///db.sqlite3"
)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

ALLOWED_REACTIONS = {"like", "love", "laugh"}


# ---------------- MODELS ----------------
class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    posts = db.relationship(
        "Post",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    __tablename__ = "post"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    reactions = db.Column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=lambda: {
            "like": 0,
            "love": 0,
            "laugh": 0,
        },
    )

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", back_populates="posts")


# ---------------- LOGIN ----------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------- HELPERS ----------------
def validate_username(username: str) -> str | None:
    username = (username or "").strip()

    if not username:
        return "Username is required."
    if len(username) < 3:
        return "Username must be at least 3 characters."
    if len(username) > 150:
        return "Username is too long."

    return None


def validate_password(password: str) -> str | None:
    if not password:
        return "Password is required."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    return None


def validate_post_content(content: str) -> str | None:
    content = (content or "").strip()

    if not content:
        return "Post content cannot be empty."
    if len(content) > 500:
        return "Post content cannot exceed 500 characters."

    return None


# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return redirect(url_for("feed" if current_user.is_authenticated else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("feed"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        username_error = validate_username(username)
        password_error = validate_password(password)

        if username_error:
            return render_template("register.html", error=username_error)
        if password_error:
            return render_template("register.html", error=password_error)

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template("register.html", error="Username already taken.")

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("feed"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.")
            return redirect(url_for("feed"))

        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html")


@app.route("/feed", methods=["GET", "POST"])
@login_required
def feed():
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        content_error = validate_post_content(content)

        if content_error:
            posts = Post.query.order_by(Post.created_at.desc()).all()
            return render_template(
                "feed.html",
                posts=posts,
                user=current_user,
                error=content_error,
            )

        post = Post(content=content, user=current_user)
        db.session.add(post)
        db.session.commit()

        flash("Post created.")
        return redirect(url_for("feed"))

    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("feed.html", posts=posts, user=current_user)


@app.route("/react/<int:post_id>", methods=["POST"])
@login_required
def react(post_id):
    data = request.get_json(silent=True) or {}
    reaction_type = data.get("reaction")

    if reaction_type not in ALLOWED_REACTIONS:
        return jsonify({"success": False, "error": "Invalid reaction type."}), 400

    post = db.session.get(Post, post_id)
    if not post:
        return jsonify({"success": False, "error": "Post not found."}), 404

    if not post.reactions:
        post.reactions = {key: 0 for key in ALLOWED_REACTIONS}

    post.reactions[reaction_type] = post.reactions.get(reaction_type, 0) + 1
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "reaction": reaction_type,
            "count": post.reactions[reaction_type],
            "reactions": post.reactions,
        }
    )


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.")
    return redirect(url_for("login"))


# ---------------- RUN ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
