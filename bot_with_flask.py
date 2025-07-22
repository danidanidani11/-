# تغییرات در بخش Flask
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Telegram Wheel Bot is running!"

@flask_app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

# تغییر در بخش اجرا
if __name__ == '__main__':
    # حل مشکل escape sequence
    import re
    price_pattern = re.compile(r"^\d+ هزار تومان$|^\d+ میلیون تومان$")
    
    # اجرای Flask با Gunicorn
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)
