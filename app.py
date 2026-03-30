import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import JSON

# ---------------- APP SETUP ----------------
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', os.urandom(24)),
    SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///db.sqlite3'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,  # Set True in production (HTTPS)
    REMEMBER_COOKIE_HTTPONLY=True
)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'


# ---------------- MODELS ----------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    posts = db.relationship('Post', backref='author', lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reactions = db.Column(JSON, nullable=False, default=lambda: {"like": 0, "love": 0, "laugh": 0})
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_rooms.id'), nullable=False)  # new

    def increment_reaction(self, reaction_type: str):
        if reaction_type not in self.reactions:
            raise ValueError("Invalid reaction type")
        updated = dict(self.reactions)
        updated[reaction_type] += 1
        self.reactions = updated
        
class ChatRoom(db.Model):
    __tablename__ = 'chat_rooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    posts = db.relationship('Post', backref='room', lazy=True)


# ---------------- LOGIN ----------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------- ROUTES ----------------
@app.route('/')
def home():
    return redirect(url_for('feed' if current_user.is_authenticated else 'login'))


# -------- AUTH --------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if len(username) < 3 or len(password) < 6:
            return render_template('register.html', error="Username ≥3 chars, Password ≥6 chars")
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Username already exists")

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return render_template('login.html', error="Invalid credentials")

        login_user(user)
        return redirect(url_for('feed'))

    return render_template('login.html')
    
@app.route('/rooms', methods=['GET', 'POST'])
@login_required
def rooms():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and not ChatRoom.query.filter_by(name=name).first():
            room = ChatRoom(name=name)
            db.session.add(room)
            db.session.commit()
        return redirect(url_for('rooms'))

    rooms = ChatRoom.query.order_by(ChatRoom.created_at.desc()).all()
    return render_template('rooms.html', rooms=rooms)

@app.route('/room/<int:room_id>', methods=['GET', 'POST'])
@login_required
def room_feed(room_id):
    room = db.session.get(ChatRoom, room_id)
    if not room:
        return render_template("error.html", message="Room not found"), 404

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if 0 < len(content) <= 300:
            post = Post(content=content, author=current_user, room=room)
            db.session.add(post)
            db.session.commit()
        return redirect(url_for('room_feed', room_id=room_id))

    posts = Post.query.filter_by(room_id=room.id).order_by(Post.created_at.desc()).all()
    return render_template('room_feed.html', room=room, posts=posts)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# -------- FEED --------
@app.route('/feed', methods=['GET', 'POST'])
@login_required
def feed():
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if 0 < len(content) <= 300:
            post = Post(content=content, author=current_user)
            db.session.add(post)
            db.session.commit()
        return redirect(url_for('feed'))

    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('feed.html', posts=posts, user=current_user)


# -------- CLEAR CHAT --------
@app.route('/clear_chat', methods=['DELETE'])
@login_required
def clear_chat():
    Post.query.delete()
    db.session.commit()
    return '', 204


# -------- REACTIONS API --------
@app.route('/react/<int:post_id>', methods=['POST'])
@login_required
def react(post_id):
    data = request.get_json(silent=True)
    if not data or 'reaction' not in data:
        return jsonify({"success": False, "error": "Missing reaction"}), 400

    post = db.session.get(Post, post_id)
    if not post:
        return jsonify({"success": False, "error": "Post not found"}), 404

    try:
        post.increment_reaction(data['reaction'])
        db.session.commit()
    except ValueError:
        return jsonify({"success": False, "error": "Invalid reaction"}), 400

    return jsonify({"success": True, "reactions": post.reactions})


# ---------------- ERROR HANDLERS ----------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", message="Page not found"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", message="Server error"), 500


# ---------------- RUN ----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
