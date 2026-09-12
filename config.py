import os
import logging
from dotenv import load_dotenv
from telebot import apihelper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")

bug_report_id = 1405966582
ch = '@kiteck_tm'
token = os.getenv("TOKEN")
db_path = os.getenv("DB_PATH", "data/bot.db")
today_audio_process = 0
today_voice_process = 0
today_video_process = 0
online = True
admins = [1405966582]

apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
apihelper.FILE_URL = "https://tapi.bale.ai/file/bot{0}/{1}"
apihelper.CONNECT_TIMEOUT = 120

video_convert_proggress = {}
words = {
    "/start/lang": {
        "fa": "برای شروع زبان خود را انتخاب کنید:\n\n@kiteck_tm",
        "en": "🌍please select your language:",
    },
    "start": {
        "fa": "🤖به ربات فایل های صوتی خوش آمدید🤖\n\nقابلیت ها:\n1️⃣: تبدیل فایل صوتی شما به وویس ✅\n2️⃣: تبدیل وویس شما به فایل صوتی ✅\n3️⃣: استخراج صدا از ویدیو ✅\n4️⃣: انتخاب نام دلخواه برای فایل✅\n\n@kiteck_tm",
        "en": "🤖Welcome to mp3 tools bot🤖\n\nBot features:\n1️⃣: Convert mp3 file to voice message✅\n2️⃣: Convert voice message to mp3 file✅\n3️⃣: Extract audio from video✅\n4️⃣: You can choose desired name for your file✅\n\n\n@kiteck_tm",
    },
    'join': {
        'fa': f'برای استفاده از این ربات لازم است ابتدا در کانال زیر عضو شوید 👇🏻\n🆔 {ch}',
        'en': f'To use this robot, you must first join the channel below 👇🏻\n🆔 {ch}',
    },
    'invalid_command': {
        'fa': '❌پیام شما قابل قبول نیست❌ \n⚠️برای استفاده از این ربات فایل صوتی، وویس یا ویدیو ارسال کنید.\n\n@kiteck_tm',
        'en': '❌Your message is not acceptable❌\n⚠️ To use this bot send your voice, mp3 file or video.\n\n@kiteck_tm',
    },
    'change_lang': {
        'fa': 'زبان شما به فارسی تغییر یافت',
        'en': 'your language changed to english',
    },
    'error': {
        'fa': 'خطایی رخ داد دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.',
        'en': 'Error happened try again later or contact support.',
    },
    "previus_process": {
        "fa": "پیام قبلی شما هنوز در حال اجراست.\n\n@kiteck_tm",
        "en": "Your previous process is still running.\n\n@kiteck_tm",
    },
    'processing': {
        "fa": "در حال پردازش....\n\n@kiteck_tm",
        "en": "processing....\n\n@kiteck_tm",
    },
    'help_text': {
        "fa": "@kiteck_tm\n\n📝فایل صوتی خود را ارسال نموده و وویس انرا دریافت کنید.\n\n📝 وویس خود را ارسال نموده برای ان نام انتخاب کنید و انرا به صورت فایل صوتی دریافت کنید.\n\n🎬 ویدیو ارسال کنید تا صدا استخراج شود.\n\n@kiteck_tm",
        "en": "@kiteck_tm \n\n📝Send your mp3 file and get it as a voice message\n\n📝Send your voice and choose a name for your mp3 file and get the voice as a mp3 file with that name\n\n🎬Send a video to extract its audio\n\n@kiteck_tm",
    },
    'file_too_large': {
        'fa': '❌فایل شما بیش از حد مجاز پلتفرم است. لطفاً فایل کوچکتری ارسال کنید.',
        'en': '❌Your file exceeds the platform limit. Please send a smaller file.',
    },
    'un_supported_file': {
        'fa': '❌تایپ فایل شما قابل قبول نیست❌\n\n@kiteck_tm',
        'en': '❌Your file type is not supported❌\n\n@kiteck_tm',
    },
    'select_name': {
        'fa': 'برای فایل خود نامی انتخاب کنید.\n\n@kiteck_tm',
        'en': 'Select a name for your file.\n\n@kiteck_tm',
    },
    'voice_to_mp3_options': {
        'fa': "✅وویس شما برای تبدیل شدن به فایل mp3 آماده است برای فایل خود یک نام انتخاب کنید 👇\n1️⃣:برای انتخاب یک اسم رندوم وارد کنید /rnd.\n2️⃣: برای کنسل کردن وارد کنید /cancel.\n\n\n@kiteck_tm",
        'en': '✅Your voice is ready to send as a mp3 file just choose a name for your file👇.\n1️⃣: If you want a random name type /rnd.\n2️⃣: If you want to cancel the process type /cancel.\n\n@kiteck_tm',
    },
    'cancel_message': {
        'fa': '✅فرایند تبدیل وویس به فایل صوتی با موفقیت کنسل شد .✅\n\n@kiteck_tm',
        'en': '✅Converting voice to mp3 file got cancelled successfully✅\n\n@kiteck_tm',
    },
    'convert_msg': {
        'fa': '⏳درحال تبدیل به وویس⏳\nدرصد پیشرفت: {} {}%\n\n@kiteck_tm',
        'en': '⏳Converting to voice⏳\nprogress: {} {}%\n\n@kiteck_tm',
    },
    'offline': {
        'fa': '🤖 ربات در حال آپدیت است و در دسترس نیست 🚧\n⏳ لطفاً بعداً امتحان کنید ⏳\n\n@kiteck_tm',
        'en': '🤖 The bot is updating and not available 🚧\n⏳ Please try again later ⏳\n\n@kiteck_tm',
    },
}
