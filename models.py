# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# 初始化 db 对象
db = SQLAlchemy()

# ----------------------
# 1. 用户表 (Users)
# ----------------------
class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))      # 纯 Email 注册才有
    google_id = db.Column(db.String(255), unique=True) # Google 登录才有
    full_name = db.Column(db.String(100))
    avatar_url = db.Column(db.Text)
    is_email_verified = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default='user', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) # 新增：自动更新时间

    # 关系：一个用户有多个行程
    trips = db.relationship('Trip', backref='user', lazy=True)
    # 关系：一个用户有多个日历同步记录

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    @property
    def is_admin(self):
        # Admin 权限通常包含 super_admin 和 admin
        return self.role in ['admin', 'super_admin']

    calendar_events = db.relationship('CalendarEvent', backref='user', lazy=True)
    def to_dict(self):
        return {
            "id": str(self.id), # 转成字符串，前端通常更喜欢字符串ID
            "name": self.full_name or "User",
            "email": self.email,
            "avatarUrl": self.avatar_url or "", # 确保前端字段名为 avatarUrl (驼峰)
            "authProvider": "google" if self.google_id else "email",
            "role": self.role  # [新增] 返回角色给前端
        }

# ----------------------
# 2. 邮箱验证码表 (EmailVerification)
# ----------------------
class EmailVerification(db.Model):
    __tablename__ = 'email_verifications'
    
    email = db.Column(db.String(255), primary_key=True)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------
# 3. 地点缓存表 (Places)
# ----------------------
class Place(db.Model):
    __tablename__ = 'places'
    
    id = db.Column(db.Integer, primary_key=True)
    # google_place_id 是去重的关键，必须唯一
    google_place_id = db.Column(db.String(255), unique=True, nullable=False)
    
    name = db.Column(db.String(255))
    address = db.Column(db.Text)
    rating = db.Column(db.Float)
    business_status = db.Column(db.String(50))
    is_open_now = db.Column(db.Boolean)
    
    # 存储 JSON 数据 (SQLite/PostgreSQL/MySQL 5.7+ 均支持 db.JSON)
    opening_hours = db.Column(db.JSON) 
    phone = db.Column(db.String(50))
    website = db.Column(db.Text)
    price_level = db.Column(db.String(50)) 
    
    # 为了兼容性，坐标存为字符串 "lat,lng"
    coordinates = db.Column(db.String(100)) 
    
    photo_reference = db.Column(db.Text) 
    review_list = db.Column(db.JSON)     
    
    cached_at = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------
# 4. 行程表 (Trips)
# ----------------------
class Trip(db.Model):
    __tablename__ = 'trips'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    title = db.Column(db.String(100))
    destination = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    
    # 新增：预算限制 (Decimal 在 Python 中对应 db.Numeric，或者简单用 db.Float)
    budget_limit = db.Column(db.Float, default=0.0) 
    status = db.Column(db.String(20), default='planning') # planning, confirmed, future
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系：一个行程有多个项目 (级联删除：删行程，项目也删)
    items = db.relationship('TripItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    # 关系：一个行程有多个消费记录
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")

# ----------------------
# 5. 行程具体项目 (TripItems)
# ----------------------
class TripItem(db.Model):
    __tablename__ = 'trip_items'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    place_id = db.Column(db.Integer, db.ForeignKey('places.id')) # 关联缓存的地点
    
    day_number = db.Column(db.Integer)
    start_time = db.Column(db.String(20)) # "14:00"
    end_time = db.Column(db.String(20))   
    type = db.Column(db.String(50))       # 'attraction', 'food'
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='confirmed')

    # 关系：一个行程项可能对应一个日历事件
    calendar_event = db.relationship('CalendarEvent', backref='trip_item', uselist=False)

# ----------------------
# [新增] 6. 消费/钱包表 (Expenses)
# ----------------------
class Expense(db.Model):
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    
    title = db.Column(db.String(100))          # "Sushi Dinner"
    amount = db.Column(db.Float, nullable=False) # 金额
    category = db.Column(db.String(50))        # "Food", "Transport"
    location_name = db.Column(db.String(255))
    
    # 交易日期，默认为今天
    transaction_date = db.Column(db.Date, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------
# [新增] 7. 日历同步表 (CalendarEvents)
# ----------------------
class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    trip_item_id = db.Column(db.Integer, db.ForeignKey('trip_items.id')) # 可为空，如果删了 item 设为 NULL
    
    google_event_id = db.Column(db.String(255)) # Google 返回的 event id
    title = db.Column(db.String(255))
    
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    
    # pending, synced, failed

    sync_status = db.Column(db.String(20), default='pending')

class Article(db.Model):
    __tablename__ = 'articles'

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id')) # 谁写的
    
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(50))   # 'Destinations', 'Tips', 'News'
    content = db.Column(db.Text)          # HTML 或 Markdown 内容
    cover_image = db.Column(db.Text)      # 封面图 URL
    
    status = db.Column(db.String(20), default='draft') # 'draft', 'published'
    views = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "views": self.views,
            "date": self.created_at.strftime("%Y-%m-%d"),
            "coverImage": self.cover_image,
            "content": self.content
        }
