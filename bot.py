import telebot
import sys
import requests
from time import time, sleep
from datetime import date
import os
import subprocess
from threading import Thread
import sqlite3
from telebot import types
from pydub import AudioSegment
import re
import json
import logging

from config import token, db_path
from config import bug_report_id, ch, admins, words, online as _online
from config import video_convert_proggress, apihelper

logger = logging.getLogger("bot")
logging.getLogger("telebot").setLevel(logging.WARNING)

spam = []
steps = {}
bot = telebot.TeleBot(token)
username = '@' + bot.get_me().username
snd = bot.send_message
edit = bot.edit_message_text
users = {}
user_voice_data = {}
user_file_names = {}
force_join = True
last_use = {}
processing = []
milestones = [25, 50, 75, 100]
last_milestone = 0
start_time = time()
word_langs = []

for i in words['start']:
    if i not in word_langs:
        word_langs.append(i)
logger.info("Bot languages loaded: %s", word_langs)


def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError as e:
                logger.warning("Failed to remove %s: %s", p, e)


def _remove_from_processing(user_id):
    try:
        if user_id in processing:
            processing.remove(user_id)
    except ValueError:
        pass


def _is_file_too_large(error: Exception) -> bool:
    msg = str(error).lower()
    return any(phrase in msg for phrase in [
        "file is too big",
        "request entity too large",
        "file too large",
        "payload too large",
        "too big",
    ])


def clear_day_usage():
    while True:
        try:
            stats = _get_stats()
            for admin_id in admins:
                try:
                    snd(
                        admin_id,
                        f'today users: {len(stats["users"])}\n'
                        f'today joins: {len(stats["joins"])}\n'
                        f'today audio: {stats["audio"]}\n'
                        f'today voice: {stats["voice"]}\n'
                        f'today video: {stats["video"]}',
                    )
                except Exception:
                    pass
            _reset_daily_stats()
            sleep(86400)
        except Exception as e:
            logger.exception("clear_day_usage failed")
            try:
                snd(bug_report_id, str(e))
            except Exception:
                pass


def report_admin(msg):
    try:
        snd(bug_report_id, str(msg))
    except Exception as e:
        logger.error("Failed to report to admin: %s", e)


# ── Database ────────────────────────────────────────────────────────────────

def _get_db():
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create_tables():
    try:
        with _get_db() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users "
                "(id TEXT PRIMARY KEY, time TEXT, lang TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_stats "
                "(date TEXT PRIMARY KEY, users TEXT, joins TEXT, "
                "audio INT, voice INT, video INT)"
            )
            conn.commit()
    except Exception as e:
        logger.exception("Failed to create tables")
        report_admin(e)


def _today():
    return date.today().isoformat()


def _ensure_today_row(conn):
    today = _today()
    conn.execute(
        "INSERT OR IGNORE INTO daily_stats (date, users, joins, audio, voice, video) "
        "VALUES (?, '', '', 0, 0, 0)", (today,)
    )
    return today


def _get_stats():
    try:
        with _get_db() as conn:
            today = _ensure_today_row(conn)
            conn.commit()
            row = conn.execute(
                "SELECT users, joins, audio, voice, video FROM daily_stats WHERE date = ?",
                (today,)
            ).fetchone()
        if row:
            users_list = row[0].split(',') if row[0] else []
            joins_list = row[1].split(',') if row[1] else []
            return {
                'users': [u for u in users_list if u],
                'joins': [j for j in joins_list if j],
                'audio': row[2],
                'voice': row[3],
                'video': row[4],
            }
    except Exception:
        logger.exception("Failed to get stats")
    return {'users': [], 'joins': [], 'audio': 0, 'voice': 0, 'video': 0}


def _increment_stat(field, user_id=None):
    try:
        with _get_db() as conn:
            today = _ensure_today_row(conn)
            if user_id:
                row = conn.execute(
                    f"SELECT {field} FROM daily_stats WHERE date = ?", (today,)
                ).fetchone()
                current = row[0] if row else ''
                ids = current.split(',') if current else []
                uid_str = str(user_id)
                if uid_str not in ids:
                    ids.append(uid_str)
                conn.execute(
                    f"UPDATE daily_stats SET {field} = ? WHERE date = ?",
                    (','.join(ids), today)
                )
            else:
                conn.execute(
                    f"UPDATE daily_stats SET {field} = {field} + 1 WHERE date = ?",
                    (today,)
                )
            conn.commit()
    except Exception:
        logger.exception("Failed to increment stat %s", field)


def _reset_daily_stats():
    try:
        with _get_db() as conn:
            today = _today()
            conn.execute("DELETE FROM daily_stats WHERE date != ?", (today,))
            conn.commit()
    except Exception:
        logger.exception("Failed to reset daily stats")


def add_to_file_ids_db(file_id, converted_id):
    pass


def check_file_id_in_db(file_id):
    return False


def add_users_to_db(user_id, ts):
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, time, lang) VALUES (?, ?, 'None')",
                (str(user_id), str(ts)),
            )
            conn.commit()
        if user_id not in users:
            users[user_id] = None
    except Exception as e:
        logger.exception("Failed to add user %s", user_id)


def db_user_ids(all_results=None):
    try:
        with _get_db() as conn:
            result = conn.execute("SELECT * FROM users").fetchall()
        if all_results is not None:
            return result
        for row in result:
            try:
                uid, _, lang = row
                users[int(uid)] = lang if lang != 'None' else None
            except (ValueError, IndexError) as e:
                logger.warning("Failed to parse user row %s: %s", row, e)
        return result
    except Exception as e:
        logger.exception("Failed to fetch user IDs")
        report_admin(e)


def update_user_lang(user_id):
    try:
        with _get_db() as conn:
            conn.execute(
                "UPDATE users SET lang = ? WHERE id = ?",
                (users[user_id], str(user_id)),
            )
            conn.commit()
    except Exception as e:
        logger.exception("Failed to update lang for user %s", user_id)
        report_admin(e)


# ── Helpers ─────────────────────────────────────────────────────────────────

def antispam():
    logger.info("Antispam thread started")
    while True:
        try:
            sleep(0.5)
            spam.clear()
        except Exception:
            sleep(1)


def check_join(user_id):
    try:
        if force_join:
            status = bot.get_chat_member(ch, user_id).status
                      
            return status != 'left'
        return True
    except Exception as e:
        logger.exception("check_join failed for %s", user_id)
        report_admin(e)
        return False


def join(user_id):
    try:
        if user_id in users:
            if users[user_id] is None:
                language_key(user_id)
                return
            user_lang = users[user_id]
        else:
            _increment_stat('joins', user_id)
            add_users_to_db(user_id, int(time()))
            language_key(user_id)
            return
        snd(user_id, words['join'][user_lang])
    except Exception as e:
        logger.exception("join failed for %s", user_id)
        report_admin(e)


def language_key(user_id):
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        farsi = types.InlineKeyboardButton('فارسی 🇮🇷', callback_data='fa')
        english = types.InlineKeyboardButton('english 🇺🇸', callback_data='en')
        markup.add(farsi, english)
        snd(
            user_id,
            f'{words["/start/lang"]["en"]}\n{words["/start/lang"]["fa"]}',
            reply_markup=markup,
        )
    except Exception as e:
        logger.exception("language_key failed for %s", user_id)


def get_total_duration(input_path):
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration_seconds = float(result.stdout.strip())
        return int(duration_seconds * 1_000_000)
    except Exception:
        return 0


def run_ffmpeg_with_progress(cmd, total_duration, label, input_path):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while True:
        line = process.stdout.readline()
        if line == '' and process.poll() is not None:
            break
        if line:
            match = re.search(r'out_time_ms=(\d+)', line)
            if match and total_duration > 0:
                current_time_us = int(match.group(1))
                percent = min((current_time_us / total_duration) * 100, 100.0)
                video_convert_proggress[input_path] = round(percent / 2)
    process.wait()
    if process.returncode != 0:
        logger.error("[%s] ffmpeg failed with code %d", label, process.returncode)


def extract_audio_ffmpeg(input_path, voice_path, mp3_path=None, bitrate="64k"):
    if input_path not in video_convert_proggress:
        video_convert_proggress[input_path] = 0
    try:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file '{input_path}' not found.")

        total_duration = get_total_duration(input_path)

        cmd_voice = [
            "ffmpeg", "-i", input_path,
            "-c:a", "libopus", "-b:a", bitrate,
            "-vbr", "on", "-compression_level", "10",
            "-frame_duration", "60", "-application", "voip",
            "-vn", "-progress", "pipe:1", "-y", voice_path,
        ]

        cmd_mp3 = [
            "ffmpeg", "-i", input_path,
            "-vn", "-ar", "44100", "-ac", "2",
            "-b:a", "128k", "-progress", "pipe:1", "-y", mp3_path,
        ] if mp3_path else None

        thread1 = Thread(target=run_ffmpeg_with_progress, args=(cmd_voice, total_duration, "Opus", input_path))
        thread1.start()

        if cmd_mp3:
            thread2 = Thread(target=run_ffmpeg_with_progress, args=(cmd_mp3, total_duration, "MP3", input_path))
            thread2.start()
            thread2.join()

        thread1.join()

    except Exception as e:
        logger.exception("extract_audio_ffmpeg failed for %s", input_path)
    finally:
        video_convert_proggress.pop(input_path, None)


# ── Callbacks ───────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    user_id = call.message.chat.id
    if user_id in spam:
        return
    spam.append(user_id)
    message_id = call.message.message_id
    try:
        user_lang = users.get(user_id)
    except Exception:
        user_lang = None

    if call.data in word_langs:
        bot.answer_callback_query(call.id, words["change_lang"][call.data])
        users[user_id] = call.data
        if check_join(user_id):
            snd(user_id, words['start'][call.data])
        else:
            Thread(target=join, args=(user_id,)).start()
        update_user_lang(user_id)
        bot.delete_message(user_id, message_id)
    else:
        bot.answer_callback_query(call.id, 'invalid query')


# ── Audio → Voice ───────────────────────────────────────────────────────────

def send_voice_func(message, wait, user_id, user_lang):
    input_path = None
    output_path = None
    try:
        media = message.audio or message.document
        file_id = media.file_id
        file_unique_id = media.file_unique_id
        file_info = bot.get_file(file_id)
        file_extension = media.mime_type
        name = getattr(media, 'file_name', None) or f'audio_{round(time())}'

        if "audio" not in file_extension:
            snd(bug_report_id, f'Unsupported format: {file_extension}')
            bot.delete_message(user_id, wait.id)
            snd(user_id, words['un_supported_file'][user_lang])
            return

        input_path = f'downloads/{name}'
        output_path = f"{name.split('.')[0]}.opus"

        file_data = bot.download_file(file_info.file_path)
        with open(input_path, 'wb') as f:
            f.write(file_data)

        convert_mp3_to_opus(
            input_path, output_path,
            msg_to_edit=wait, id=user_id, user_lang=user_lang,
        )

        with open(output_path, 'rb') as f:
            voice_file_sent = bot.send_voice(user_id, f, caption='@KITECK_TM')

        bot.delete_message(user_id, wait.id)

    except Exception as e:
        logger.exception("send_voice_func failed for user %s", user_id)
        bot.delete_message(user_id, wait.id)
        if _is_file_too_large(e):
            snd(user_id, words['file_too_large'][user_lang])
        else:
            snd(user_id, words['error'][user_lang])
    finally:
        _remove_from_processing(user_id)
        _cleanup(input_path, output_path)
        try:
            bot.delete_message(user_id, wait.id)
        except Exception:
            pass


# ── Voice → MP3 ─────────────────────────────────────────────────────────────

def send_mp3_func(message, wait, user_id, user_lang, name):
    input_path = None
    try:
        if user_id in processing:
            snd(user_id, words["previus_process"][user_lang])
            return
        processing.append(user_id)
        try:
            bot.delete_message(user_id, wait.id)
        except Exception:
            pass
        wait = snd(user_id, words['processing'][user_lang])

        file_id = message.voice.file_id
        file_info = bot.get_file(file_id)

        input_path = f'downloads/{name}'
        file_data = bot.download_file(file_info.file_path)
        with open(input_path, 'wb') as f:
            f.write(file_data)

        with open(input_path, 'rb') as f:
            voice_file = bot.send_audio(user_id, f, caption='@KITECK_TM', title=f'{name}.mp3')

        bot.delete_message(user_id, wait.id)

    except Exception as e:
        logger.exception("send_mp3_func failed for user %s", user_id)
        try:
            bot.delete_message(user_id, wait.id)
        except Exception:
            pass
        if _is_file_too_large(e):
            snd(user_id, words['file_too_large'][user_lang])
        else:
            snd(user_id, words['error'][user_lang])
    finally:
        steps.pop(user_id, None)
        _remove_from_processing(user_id)
        _cleanup(input_path)
        try:
            bot.delete_message(user_id, wait.id)
        except Exception:
            pass


# ── Video → Voice + MP3 ────────────────────────────────────────────────────

def process_video_send_audio(user_id, file_id, reply_message_id, wait, file_unique_id):
    video_path = None
    voice_path = None
    mp3_path = None
    try:
        file_info = bot.get_file(file_id)
        video_path = f"video_{round(time())}.mp4"

        file_data = bot.download_file(file_info.file_path)
        with open(video_path, 'wb') as f:
            f.write(file_data)

        voice_path = f"voice_{round(time())}.ogg"
        mp3_path = f"audio_{round(time())}.mp3"

        Thread(target=extract_audio_ffmpeg, args=(video_path, voice_path, mp3_path)).start()

        while video_path in video_convert_proggress:
            percent_complete = video_convert_proggress.get(video_path)
            if percent_complete is not None:
                for milestone in sorted(milestones):
                    if milestone == percent_complete:
                        try:
                            bar = '▓' * (milestone // 4)
                            bot.edit_message_text(
                                words['convert_msg'][users[user_id]].format(bar, milestone),
                                user_id, wait.id,
                            )
                        except Exception:
                            pass
                        break
            sleep(0.5)

        bot.edit_message_text(
            words['convert_msg'][users[user_id]].format('▓' * 25, 100),
            user_id, wait.id,
        )

        voice_id = None
        audio_id = None

        with open(voice_path, "rb") as voice:
            voice_file_sent = bot.send_voice(
                user_id, voice, reply_to_message_id=reply_message_id, caption='@KITECK_TM',
            )
            voice_id = voice_file_sent.voice.file_id
        bot.delete_message(user_id, wait.id)

        with open(mp3_path, "rb") as mp3_file:
            audio_file_sent = bot.send_audio(
                user_id, mp3_file, reply_to_message_id=reply_message_id,
                caption='@KITECK_TM', title='video_audio.mp3',
            )
            audio_id = audio_file_sent.audio.file_id

    except Exception as e:
        logger.exception("process_video_send_audio failed for user %s", user_id)
        if _is_file_too_large(e):
            snd(user_id, words['file_too_large'][users.get(user_id, 'en')])
        else:
            snd(user_id, words['error'][users.get(user_id, 'en')])
    finally:
        _remove_from_processing(user_id)
        _cleanup(video_path, voice_path, mp3_path)


# ── Conversion utilities ────────────────────────────────────────────────────

def convert_mp3_to_opus(input_path, output_path, msg_to_edit, id, user_lang, bitrate='24k'):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file '{input_path}' not found.")
    if os.path.exists(output_path):
        os.remove(output_path)

    cmd = [
        'ffmpeg', '-i', input_path,
        '-c:a', 'libopus', '-b:a', bitrate,
        '-vbr', 'on', '-compression_level', '10',
        '-frame_duration', '60', '-application', 'voip',
        '-progress', 'pipe:1', output_path,
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        total_duration = get_total_duration(input_path)
        milestone_idx = 0
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                match = re.search(r'out_time_ms=(\d+)', output)
                if match:
                    current_time_ms = int(match.group(1))
                    percent_complete = (current_time_ms / total_duration) * 100 if total_duration > 0 else 0
                    if milestone_idx < len(milestones) and percent_complete >= milestones[milestone_idx]:
                        milestone = milestones[milestone_idx]
                        milestone_idx += 1
                        max_length = 20
                        count = int((milestone / 100) * max_length)
                        bar = '▓' * count
                        try:
                            bot.edit_message_text(
                                words['convert_msg'][user_lang].format(bar, milestone),
                                id, msg_to_edit.id,
                            )
                        except Exception:
                            pass
            sleep(0.5)
        process.wait()
        logger.info("Converted %s -> %s", input_path, output_path)
        return output_path

    except Exception as e:
        logger.exception("convert_mp3_to_opus failed")
        if os.path.exists(output_path):
            os.remove(output_path)
        cmd_fallback = [
            'ffmpeg', '-i', input_path,
            '-c:a', 'libopus', '-b:a', bitrate,
            '-vbr', 'on', '-compression_level', '10',
            '-frame_duration', '60', '-application', 'voip',
            output_path,
        ]
        subprocess.run(cmd_fallback, check=True)
        return output_path


# ── Admin commands ──────────────────────────────────────────────────────────

def save_users(user_id):
    try:
        response = {}
        users_data = db_user_ids(all_results=True)
        for data in users_data:
            uid, ts, lang = data
            if uid not in response:
                response[uid] = {}
            response[uid]["lang"] = lang
            response[uid]["time"] = ts
        with open("users.json", 'w') as f:
            json.dump(response, f, indent=4)
        with open("users.json", 'rb') as f:
            bot.send_document(user_id, f, caption="users.json")
        snd(user_id, 'saved')
    except Exception as e:
        logger.exception("save_users failed")
    finally:
        _cleanup("users.json")


def forward_message_to_all_users(chat_id, msg_id, user_ids=None):
    successful_count = 0
    failed_count = 0
    n = 0
    if not user_ids:
        user_ids = list(users.keys())
    for user_id in user_ids:
        if n > 1000:
            n = 0
            sleep(60)
            try:
                snd(chat_id, f"Forwarded {successful_count} messages successfully.")
            except Exception as e:
                logger.error("Failed to send progress update: %s", e)
        try:
            bot.forward_message(user_id, chat_id, msg_id)
            successful_count += 1
            n += 1
        except Exception as e:
            failed_count += 1
            sleep(1)
            if "Too Many Requests" in str(e):
                try:
                    limit_seconds = int(str(e).split("retry after")[1].strip())
                except (IndexError, ValueError):
                    limit_seconds = 3600
                logger.warning("Rate limit hit, sleeping %ds", limit_seconds)
                try:
                    snd(chat_id, f"Rate limit reached. Sleeping for {limit_seconds} seconds.")
                except Exception:
                    pass
                sleep(limit_seconds + 60)
            elif "bot was blocked by the user" in str(e):
                logger.info("Bot blocked by user %s, skipping", user_id)
            else:
                logger.warning("Forward failed for %s: %s", user_id, e)
    snd(chat_id, f"Message forwarding completed. Successful: {successful_count}, Failed: {failed_count}")


# ── Message handlers ────────────────────────────────────────────────────────

@bot.message_handler(content_types=['video'])
def video_handler(message):
    _increment_stat('video')
    user_id = message.from_user.id

    if user_id not in users:
        add_users_to_db(user_id, int(time()))
        language_key(user_id)
        return
    if users[user_id] is None:
        language_key(user_id)
        return
    if not online and user_id not in admins:
        snd(user_id, words['offline']['en'])
        return

    _increment_stat('users', user_id)

    try:
        user_lang = users[user_id]
        if user_id in processing:
            snd(user_id, words["previus_process"][user_lang])
            return

        processing.append(user_id)
        wait = bot.reply_to(message, words['processing'].get(user_lang, 'en'))
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id

        Thread(
            target=process_video_send_audio,
            args=(user_id, file_id, message.message_id, wait, file_unique_id),
        ).start()

    except Exception as e:
        logger.exception("video_handler failed")
        _remove_from_processing(user_id)


@bot.message_handler(content_types=['audio'])
def audio_handler(message):
    _increment_stat('audio')
    user_id = message.from_user.id

    if user_id not in users:
        add_users_to_db(user_id, int(time()))
        language_key(user_id)
        return
    if users[user_id] is None:
        language_key(user_id)
        return
    if not online and user_id not in admins:
        snd(user_id, words['offline'][users.get(user_id, 'en')])
        return

    _increment_stat('users', user_id)

    try:
        user_lang = users[user_id]
        if user_id in processing:
            snd(user_id, words["previus_process"][user_lang])
            return
        processing.append(user_id)
        wait = bot.reply_to(message, words['processing'][user_lang])
        Thread(target=send_voice_func, args=(message, wait, user_id, user_lang)).start()
    except Exception as e:
        logger.exception("audio_handler failed")
        _remove_from_processing(user_id)


@bot.message_handler(content_types=['document'])
def document_handler(message):
    doc = message.document
    file_name = (doc.file_name or '').lower()
    mime = (doc.mime_type or '').lower()
    is_audio_doc = (
        mime.startswith('audio/')
        or file_name.endswith(('.mp3', '.ogg', '.wav', '.opus', '.m4a', '.flac', '.aac', '.amr'))
    )
    if not is_audio_doc:
        return

    _increment_stat('audio')
    user_id = message.from_user.id

    if user_id not in users:
        add_users_to_db(user_id, int(time()))
        language_key(user_id)
        return
    if users[user_id] is None:
        language_key(user_id)
        return
    if not online and user_id not in admins:
        snd(user_id, words['offline'][users.get(user_id, 'en')])
        return

    _increment_stat('users', user_id)

    try:
        user_lang = users[user_id]
        if user_id in processing:
            snd(user_id, words["previus_process"][user_lang])
            return
        processing.append(user_id)
        wait = bot.reply_to(message, words['processing'][user_lang])
        Thread(target=send_voice_func, args=(message, wait, user_id, user_lang)).start()
    except Exception as e:
        logger.exception("document_handler failed")
        _remove_from_processing(user_id)


@bot.message_handler(content_types=['voice'])
def voice_handler(message):
    _increment_stat('voice')
    user_id = message.from_user.id

    if user_id not in users:
        add_users_to_db(user_id, int(time()))
        language_key(user_id)
        return
    if users[user_id] is None:
        language_key(user_id)
        return
    if not online and user_id not in admins:
        snd(user_id, words['offline'][users.get(user_id, 'en')])
        return

    _increment_stat('users', user_id)

    try:
        user_lang = users[user_id]
        wait = bot.reply_to(message, words['processing'][user_lang])
        wait = bot.edit_message_text(words['voice_to_mp3_options'][user_lang], user_id, wait.id)
        user_voice_data[user_id] = {'wait': wait, 'message': message}
        steps[user_id] = 'get_name'
    except Exception as e:
        logger.exception("voice_handler failed")
        _remove_from_processing(user_id)


@bot.message_handler(func=lambda message: True)
def msg_handler(message):
    global online
    user_id = message.from_user.id

    _increment_stat('users', user_id)

    try:
        txt = message.text
        if user_id in spam:
            return
        spam.append(user_id)

        if user_id not in users:
            add_users_to_db(user_id, int(time()))
            language_key(user_id)
            return
        if users[user_id] is None:
            language_key(user_id)
            return

        user_lang = users[user_id]

        if not online and user_id not in admins:
            snd(user_id, words['offline'][user_lang])
            return

        if check_join(user_id) or txt == '/language':
            if txt in ['/language', 'زبان', '/start']:
                if txt == '/start':
                    snd(user_id, words['start'][user_lang])
                else:
                    language_key(user_id)

            elif txt in ['/help', "help 💡", "راهنما 💡"]:
                snd(user_id, words['help_text'][user_lang])

            elif txt == '/cancel':
                if user_id in steps and steps[user_id] == 'get_name':
                    try:
                        bot.delete_message(user_id, user_voice_data[user_id]['wait'].id)
                    except Exception:
                        pass
                    snd(user_id, words['cancel_message'][user_lang])
                    del steps[user_id]
                    _remove_from_processing(user_id)
                else:
                    snd(user_id, words['invalid_command'][user_lang])

            elif txt == '/rnd':
                if user_id in steps and steps[user_id] == 'get_name':
                    random_name = str(round(time()))
                    Thread(target=send_mp3_func, args=(
                        user_voice_data[user_id]['message'],
                        user_voice_data[user_id]['wait'],
                        user_id, user_lang, random_name,
                    )).start()
                else:
                    snd(user_id, words['invalid_command'][user_lang])

            else:
                if user_id in steps and steps[user_id] == 'get_name':
                    Thread(target=send_mp3_func, args=(
                        user_voice_data[user_id]['message'],
                        user_voice_data[user_id]['wait'],
                        user_id, user_lang, txt,
                    )).start()
                    return

                if user_id in admins:
                    if txt in ['status', 'amar', 'امار']:
                        stats = _get_stats()
                        snd(
                            user_id,
                            f'users:{len(users)}\nadmins:{admins}\n'
                            f'Today usage: {len(stats["users"])}\nToday join: {len(stats["joins"])}\n'
                            f'today audio: {stats["audio"]}\n'
                            f'today voice: {stats["voice"]}\n'
                            f'today video: {stats["video"]}',
                        )
                    elif txt == 'online':
                        online = True
                        snd(user_id, 'ربات آنلاین شد.')
                    elif txt == 'offline':
                        online = False
                        snd(user_id, 'ربات افلاین شد.')
                    elif txt in ['fwdall', '/fwdall']:
                        Thread(target=forward_message_to_all_users, args=(
                            user_id, message.reply_to_message.id,
                        )).start()
                        snd(user_id, 'Start sending message to all users')
                    elif txt == 'save':
                        Thread(target=save_users, args=(user_id,)).start()
                    else:
                        snd(user_id, words['invalid_command'][user_lang])
        else:
            Thread(target=join, args=(user_id,)).start()

    except Exception as e:
        logger.exception("msg_handler failed for user %s", user_id)
        snd(user_id, 'error !')


# ── Main ────────────────────────────────────────────────────────────────────

online = _online

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    create_tables()
    db_user_ids()
    Thread(target=clear_day_usage, daemon=True).start()
    Thread(target=antispam, daemon=True).start()
    logger.info("Bot started, loaded %d users", len(users))
    bot.infinity_polling(timeout=20)
