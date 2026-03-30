from datetime import datetime
import os

from sqlalchemy import JSON
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)

# ✅ UPDATED: use environment variables (with safe fallback)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///db.sqlite3"
)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)

# ---------------- MODELS ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(150), nullable=False)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(200))

    reactions = db.Column(JSON, default={
        "like": 0,
        "love": 0,
        "laugh": 0
    })

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='posts')


# ---------------- LOGIN ----------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- ROUTES ----------------
@app.route('/react/<int:post_id>', methods=['POST'])
def react(post_id):
    data = request.get_json()

    if not data or 'reaction' not in data:
        return jsonify({"success": False, "error": "Invalid request"}), 400

    reaction_type = data['reaction']
    post = Post.query.get(post_id)

    if not post:
        return jsonify({"success": False, "error": "Post not found"}), 404

    if reaction_type not in post.reactions:
        return jsonify({"success": False, "error": "Invalid reaction"}), 400

    post.reactions = dict(post.reactions)
    post.reactions[reaction_type] += 1
    db.session.commit()

    return jsonify({
        "success": True,
        "count": post.reactions[reaction_type]
    })


@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':

        existing_user = User.query.filter_by(
            username=request.form['username']
        ).first()

        if existing_user:
            return render_template('register.html', error="Username already taken")

        user = User(
            username=request.form['username'],
            password=request.form['password']
        )

        db.session.add(user)
        db.session.commit()

        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            login_user(user)
            return redirect(url_for('feed'))
    return render_template('login.html')


@app.route('/feed', methods=['GET', 'POST'])
@login_required
def feed():
    if request.method == 'POST':
        post = Post(content=request.form['content'], user=current_user)
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('feed'))

    posts = Post.query.order_by(Post.id.desc()).all()
    return render_template('feed.html', posts=posts, user=current_user)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------------- RUN ----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
