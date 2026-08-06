import asyncio
import csv
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import qrcode
import requests
from flask import Flask, jsonify, request, send_from_directory
from PIL import Image, ImageDraw, ImageFont
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram import InputFile
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

import database

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8997438789:AAHNsJRI0SxRiAfq1yc0vVCYFbZaEgYUm6s")
BASE_URL = os.getenv("BASE_URL", "https://bongprak.top").rstrip("/")
_owner_raw = re.sub(r"\D", "", os.environ.get("OWNER_ID", "6745205121") or "")
OWNER_ID = int(_owner_raw or "6745205121")
SHOP_ID = 1
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
FLASK_PORT = int(os.environ.get("PORT", 5000))
LEGACY_PUBLIC_HOSTS = (
    "diner-copied-herbal.ngrok-free.dev",
    "ngrok-free.dev",
    "ngrok.io",
)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LOGO_PATH = os.path.join(STATIC_DIR, "logo.png")
BG_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "backgrounds")
MENU_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "menu")
KHQR_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "khqr")
PAYMENTS_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "payments")
REVIEWS_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "reviews")
POSTERS_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static", "posters")
FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
# Preferred project fonts (Noto) — language-specific files avoid tofu boxes
FONT_FILES = {
    "en": "NotoSans-Regular.ttf",
    "zh": "NotoSansSC-Regular.otf",
    "km": "NotoSansKhmer-Regular.ttf",
}
DEFAULT_PROJECT_FONT = "NotoSans-Regular.ttf"

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Conversation states
(
    WAITING_SHOP_NAME,
    WAITING_PRIMARY_COLOR,
    WAITING_BACKGROUND_COLOR,
    WAITING_LOGO,
    WAITING_CUSTOM_COLOR,
    WAITING_BACKGROUND_IMAGE,
    WAITING_ITEM_CATEGORY,
    WAITING_ITEM_NAME,
    WAITING_ITEM_PRICE,
    WAITING_ITEM_VEGETARIAN,
    WAITING_ITEM_PHOTO,
    WAITING_KHQR,
    WAITING_PAYMENT_AMOUNT,
    WAITING_COUPON_TYPE,
    WAITING_COUPON_VALUE,
    WAITING_COUPON_MIN_ORDER,
    WAITING_COUPON_USAGE_LIMIT,
    WAITING_COUPON_EXPIRY,
    WAITING_POSTER_TYPE,
    WAITING_PROMO_TEXT,
    WAITING_PROMO_BG,
    WAITING_GROUP_INVITE,
    WAITING_EXPORT_START,
    WAITING_EXPORT_END,
) = range(24)

PRESET_COLORS = [
    ("red", "🔴", "#F44336"),
    ("orange", "🟠", "#FF9800"),
    ("yellow", "🟡", "#FFEB3B"),
    ("green", "🟢", "#4CAF50"),
    ("blue", "🔵", "#2196F3"),
    ("purple", "🟣", "#9C27B0"),
    ("black", "⚫", "#212121"),
    ("white", "⚪", "#FFFFFF"),
]

CATEGORY_I18N = {
    "drinks": {"en": "Drinks", "km": "ភេសជ្ជៈ", "zh": "饮料"},
    "food": {"en": "Food", "km": "ម្ហូប", "zh": "食品"},
    "dessert": {"en": "Dessert", "km": "បង្អែម", "zh": "甜品"},
    "desserts": {"en": "Desserts", "km": "បង្អែម", "zh": "甜品"},
    "coffee": {"en": "Coffee", "km": "កាហ្វេ", "zh": "咖啡"},
    "tea": {"en": "Tea", "km": "តែ", "zh": "茶"},
}

BOT_TRANSLATIONS = {
    "en": {
        "owner_only": "Only the bot owner can use this command.",
        "shop_not_found": "Shop settings not found.",
        "settings_header": "Shop settings:",
        "not_set": "(not set)",
        "label_en": "EN",
        "label_km": "KM",
        "label_zh": "ZH",
        "label_primary": "Primary color",
        "label_background": "Background color",
        "label_logo": "Logo",
        "choose_option": "Choose an option below (or /cancel):",
        "btn_shop_name": "Set Shop Name (trilingual)",
        "btn_primary_color": "Set Primary Color",
        "btn_background_color": "Set Background Color",
        "btn_upload_logo": "Upload Logo",
        "btn_upload_khqr": "Upload KHQR Code",
        "btn_background_image": "Set Background Image",
        "btn_add_item": "Add Menu Item",
        "label_background_image": "Background image",
        "label_khqr": "KHQR code",
        "prompt_khqr": "Send a photo of your KHQR payment code.\nSend /cancel to abort.",
        "khqr_need_photo": "Please send a photo (not a file). Send /cancel to abort.",
        "khqr_uploaded": "KHQR code uploaded.\nURL: {url}",
        "khqr_missing": "No KHQR code uploaded yet. Open /settings and upload one first.",
        "btn_generate_payment": "Generate Payment Page",
        "prompt_payment_amount": "Enter the exact amount to charge (in USD):\nSend /cancel to abort.",
        "invalid_payment_amount": "Invalid amount. Send a number like 2.50:",
        "payment_page_sent": "Payment page sent to customer.",
        "payment_send_failed": "Could not send payment page to the customer. Check that they started the bot.",
        "customer_id_missing": "This order has no customer Telegram ID, so payment cannot be sent.",
        "order_not_awaiting_payment": "Order {order_no} is not awaiting payment (status: {status}).",
        "order_marked_paid": "Order {order_no} marked as paid.",
        "payment_amount_label": "Charge amount: ${amount:.2f}",
        "payment_transfer_text": "Please transfer ${amount:.2f} to {shop_name}",
        "customer_order_paid": "Your order {order_no} has been paid. Thank you!",
        "customer_order_cancelled": "Your order {order_no} has been cancelled.",
        "prompt_shop_name": (
            "Send shop names in format:\nEnglish|Khmer|Chinese\n\n"
            "Example:\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺\n\nSend /cancel to abort."
        ),
        "choose_primary_color": "Choose a primary color (or Custom /cancel):",
        "choose_background_color": "Choose a background color (or Custom /cancel):",
        "prompt_custom_color": "Send a custom hex color (e.g. #FF5722).\nSend /cancel to abort.",
        "prompt_logo": "Send a photo to use as the shop logo.\nSend /cancel to abort.",
        "prompt_background_image": (
            "Send a photo to use as the shop background image.\nSend /cancel to abort."
        ),
        "background_image_need_photo": (
            "Please send a photo (not a file). Send /cancel to abort."
        ),
        "background_image_uploaded": "Background image uploaded.\nURL: {url}",
        "prompt_item_category": (
            "Send the category name (e.g. Drinks, Food).\nSend /cancel to abort."
        ),
        "prompt_item_name": (
            "Send the item name in format:\nEnglish|Khmer|Chinese\n\n"
            "Example:\nCoffee|កាហ្វេ|咖啡\n\nSend /cancel to abort."
        ),
        "prompt_item_price": "Send the price as a number (e.g. 2.5).\nSend /cancel to abort.",
        "prompt_item_photo": (
            "Send an optional photo for this item, or send /skip to continue without a photo."
        ),
        "invalid_item_name": (
            "Invalid format. Send exactly:\nEnglish|Khmer|Chinese\n\n"
            "Example:\nCoffee|កាហ្វេ|咖啡"
        ),
        "invalid_item_price": "Invalid price. Send a number like 2.5:",
        "item_added": (
            "Menu item added!\n\n"
            "Category: {category}\n"
            "Name: {name}\n"
            "Price: ${price:.2f}\n"
            "Image: {image}"
        ),
        "no_image": "(none)",
        "btn_skip": "Skip photo",
        "invalid_shop_name": (
            "Invalid format. Send exactly:\nEnglish|Khmer|Chinese\n\n"
            "Example:\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺"
        ),
        "invalid_color": "Invalid color. Send a hex code like #FF5722:",
        "shop_names_updated": "Shop names updated.",
        "primary_updated": "Primary color updated to {value}.",
        "background_updated": "Background color updated to {value}.",
        "logo_need_photo": "Please send a photo (not a file). Send /cancel to abort.",
        "logo_uploaded": "Logo uploaded.\nURL: {url}",
        "cancelled": "Cancelled. Send /settings to edit again.",
        "preview_message": "Preview your shop Mini App:\n\n{link}",
        "btn_preview": "Preview Shop",
        "btn_deep_link": "Open Deep Link",
        "btn_custom": "✏️ Custom",
        "color_red": "Red",
        "color_orange": "Orange",
        "color_yellow": "Yellow",
        "color_green": "Green",
        "color_blue": "Blue",
        "color_purple": "Purple",
        "color_black": "Black",
        "color_white": "White",
        "customer_unknown": "Unknown",
        "btn_confirm_payment": "Confirm Payment",
        "btn_cancel_order": "Cancel Order",
        "order_manage_header": "Order {order_no}",
        "order_status": "Status: {status}",
        "order_payment_confirmed": "Payment confirmed for order {order_no}.",
        "order_cancelled_msg": "Order {order_no} cancelled.",
        "order_not_found": "Order not found.",
        "welcome_message": "Welcome! Tap the button below to open the menu.",
        "btn_open_menu": "Open Menu",
        "referral_saved": "Referral linked! Complete your first order to earn rewards.",
        "referral_self": "You cannot use your own referral link.",
        "coupon_create_prompt_type": "Create coupon — choose type:",
        "btn_coupon_fixed": "Fixed $ amount",
        "btn_coupon_percent": "Percent %",
        "coupon_prompt_value_fixed": "Send the fixed discount amount in USD (e.g. 2.5):",
        "coupon_prompt_value_percent": "Send the percent discount (e.g. 10 for 10%):",
        "coupon_prompt_min_order": "Send the minimum order amount in USD (0 for none):",
        "coupon_prompt_usage_limit": "Send the usage limit (e.g. 50):",
        "coupon_prompt_expiry": "Send expiry in days from now (0 = no expiry):",
        "coupon_invalid_number": "Invalid number. Please try again:",
        "coupon_created": (
            "Coupon created!\n\n"
            "Code: {code}\n"
            "Type: {type}\n"
            "Value: {value}\n"
            "Min order: ${min_order:.2f}\n"
            "Usage limit: {usage_limit}\n"
            "Expires: {expires}"
        ),
        "coupon_no_expiry": "Never",
        "mycoupons_empty": "You have no unused coupons.",
        "mycoupons_header": "Your unused coupons:",
        "mycoupons_line_fixed": "• {code}: ${value:.2f} off (min ${min_order:.2f}){expires}",
        "mycoupons_line_percent": "• {code}: {value:.0f}% off (min ${min_order:.2f}){expires}",
        "mycoupons_expires": " — expires {date}",
        "welcome_coupon_granted": "Gift: coupon {code} (${value:.2f} off) added to your account! Use /mycoupons",
        "referral_reward_granted": "Referral reward: coupon {code} (${value:.2f} off)! Use /mycoupons",
        "review_invite": "Rate your meal and earn points!",
        "btn_leave_review": "Leave a Review",
        "reviews_empty": "No reviews yet.",
        "reviews_header": "Recent reviews:",
        "review_line": "#{id} ⭐{rating}/5 — {name}\n{comment}",
        "btn_feature_review": "Feature",
        "btn_delete_review": "Delete",
        "review_featured": "Review #{id} marked as featured.",
        "review_deleted": "Review #{id} deleted.",
        "review_not_found": "Review not found.",
        "tiktok_owner_notify": (
            "New TikTok submission #{id}\n"
            "User: {user_id}\n"
            "Order: {order_no}\n"
            "Video: {url}"
        ),
        "btn_approve_tiktok": "Approve",
        "btn_reject_tiktok": "Reject",
        "tiktok_approved": "TikTok #{id} approved. Coupon sent to customer.",
        "tiktok_rejected": "TikTok #{id} rejected.",
        "tiktok_already_handled": "This submission was already handled.",
        "tiktok_reward_user": "Your TikTok was approved! Coupon {code} ($5 off). Use /mycoupons",
        "tiktok_reject_user": "Your TikTok submission was not approved.",
        "poster_choose_type": "Choose poster type:",
        "btn_poster_table_qr": "Table QR",
        "btn_poster_promotion": "Promotion",
        "poster_prompt_promo_text": "Send the promotion text for the poster.\n/cancel to abort.",
        "poster_prompt_bg": (
            "Send an optional background photo, or /skip to use a solid color."
        ),
        "poster_ready": "Poster ready.",
        "poster_failed": "Failed to generate poster.",
        "poster_need_bot_username": "Bot username unavailable. Try again later.",
        "poster_khqr_missing": "Upload a KHQR code in /settings first.",
        "prompt_item_vegetarian": (
            "Is this vegetarian? Reply yes or no.\nSend /cancel to abort."
        ),
        "invalid_item_vegetarian": "Please reply yes or no:",
        "festival_list_header": "Festivals (tap to activate):",
        "festival_line": (
            "{name}\n{start} → {end} · {discount}% off"
            "{veg}"
        ),
        "festival_veg_tag": " · vegetarian focus",
        "btn_activate_festival": "Activate",
        "btn_clear_festival": "Clear active festival",
        "festival_activated": "Activated: {name} ({discount}% off)",
        "festival_cleared": "Festival deactivated.",
        "festival_none": "No festivals configured.",
        "festival_active_label": "Active now: {name}",
        "festival_not_active": "No festival active.",
        "btn_group_invite": "Set Group Invite Link",
        "label_group_invite": "Group invite link",
        "prompt_group_invite": (
            "Send your Telegram group invite link (https://t.me/+...).\n"
            "Send /cancel to abort."
        ),
        "invalid_group_invite": "Please send a valid https://t.me/ link:",
        "group_invite_saved": "Group invite link saved.",
        "queue_empty": "Queue is empty.",
        "queue_header": "Current queue:",
        "queue_line": "#{number} · party {size} · {status} · user {user_id}",
        "btn_queue_next": "Next",
        "btn_queue_call": "Call #{number}",
        "queue_advanced": "Advanced #{number} to ordering. User notified: {notified}",
        "queue_called": "Called #{number} (ready). User notified: {notified}",
        "queue_no_waiting": "No waiting guests.",
        "queue_notify_ordering": (
            "It's your turn! Queue #{number}. You can pre-order in the Mini App now."
        ),
        "queue_notify_ready": "Your table is ready! Queue #{number}. Please come to the counter.",
        "queue_notify_failed": "no (ask guest to /start the bot)",
        "queue_notify_ok": "yes",
        "stats_header": "Stats ({period}):",
        "stats_orders": "Orders: {count}",
        "stats_revenue": "Revenue: ${revenue:.2f}",
        "stats_top_items": "Top items:",
        "stats_item_line": "• {name} × {qty}",
        "stats_no_items": "(none)",
        "export_prompt_start": "Export CSV — send start date (YYYY-MM-DD):",
        "export_prompt_end": "Send end date (YYYY-MM-DD):",
        "export_invalid_date": "Invalid date. Use YYYY-MM-DD:",
        "export_empty": "No orders in that range.",
        "export_ready": "Orders export {start} → {end}",
        "export_usage": "Usage: /export YYYY-MM-DD YYYY-MM-DD\nOr send /export and follow prompts.",
    },
    "km": {
        "owner_only": "មានតែម្ចាស់បូតប៉ុណ្ណោះដែលអាចប្រើពាក្យបញ្ជានេះ។",
        "shop_not_found": "រកមិនឃើញការកំណត់ហាងទេ។",
        "settings_header": "ការកំណត់ហាង:",
        "not_set": "(មិនទាន់កំណត់)",
        "label_en": "EN",
        "label_km": "KM",
        "label_zh": "ZH",
        "label_primary": "ពណ៌ចម្បង",
        "label_background": "ពណ៌ផ្ទៃខាងក្រោយ",
        "label_logo": "ឡូហ្គោ",
        "choose_option": "ជ្រើសរើសជម្រើសខាងក្រោម (ឬ /cancel):",
        "btn_shop_name": "កំណត់ឈ្មោះហាង (បីភាសា)",
        "btn_primary_color": "កំណត់ពណ៌ចម្បង",
        "btn_background_color": "កំណត់ពណ៌ផ្ទៃខាងក្រោយ",
        "btn_upload_logo": "ផ្ទុកឡូហ្គោ",
        "btn_upload_khqr": "ផ្ទុកកូដ KHQR",
        "btn_background_image": "កំណត់រូបភាពផ្ទៃខាងក្រោយ",
        "btn_add_item": "បន្ថែមមុខម្ហូប",
        "label_background_image": "រូបភាពផ្ទៃខាងក្រោយ",
        "label_khqr": "កូដ KHQR",
        "prompt_khqr": "ផ្ញើរូបថតកូដ KHQR សម្រាប់ទូទាត់។\nផ្ញើ /cancel ដើម្បីបោះបង់។",
        "khqr_need_photo": "សូមផ្ញើរូបថត (មិនមែនឯកសារ)។ ផ្ញើ /cancel ដើម្បីបោះបង់។",
        "khqr_uploaded": "បានផ្ទុកកូដ KHQR។\nURL: {url}",
        "khqr_missing": "មិនទាន់មានកូដ KHQR ទេ។ បើក /settings ហើយផ្ទុកជាមុនសិន។",
        "btn_generate_payment": "បង្កើតទំព័រទូទាត់",
        "prompt_payment_amount": "បញ្ចូលចំនួនទឹកប្រាក់ពិតប្រាកដ (USD):\nផ្ញើ /cancel ដើម្បីបោះបង់។",
        "invalid_payment_amount": "ចំនួនមិនត្រឹមត្រូវ។ ផ្ញើលេខដូច 2.50:",
        "payment_page_sent": "បានផ្ញើទំព័រទូទាត់ទៅអតិថិជន។",
        "payment_send_failed": "មិនអាចផ្ញើទំព័រទូទាត់ទៅអតិថិជនបានទេ។ ត្រូវប្រាកដថាពួកគេបានចាប់ផ្តើមបូត។",
        "customer_id_missing": "ការកម្មង់នេះគ្មាន Telegram ID របស់អតិថិជន ដូច្នេះមិនអាចផ្ញើការទូទាត់បានទេ។",
        "order_not_awaiting_payment": "ការកម្មង់ {order_no} មិនកំពុងរង់ចាំការទូទាត់ទេ (ស្ថានភាព: {status})។",
        "order_marked_paid": "ការកម្មង់ {order_no} បានសម្គាល់ថាបានបង់។",
        "payment_amount_label": "ចំនួនគិតប្រាក់: ${amount:.2f}",
        "payment_transfer_text": "សូមផ្ទេរ ${amount:.2f} ទៅ {shop_name}",
        "customer_order_paid": "ការកម្មង់ {order_no} របស់អ្នកបានបង់រួចហើយ។ អរគុណ!",
        "customer_order_cancelled": "ការកម្មង់ {order_no} របស់អ្នកត្រូវបានបោះបង់។",
        "prompt_shop_name": (
            "ផ្ញើឈ្មោះហាងតាមទម្រង់:\nEnglish|Khmer|Chinese\n\n"
            "ឧទាហរណ៍:\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺\n\nផ្ញើ /cancel ដើម្បីបោះបង់។"
        ),
        "choose_primary_color": "ជ្រើសរើសពណ៌ចម្បង (ឬ Custom /cancel):",
        "choose_background_color": "ជ្រើសរើសពណ៌ផ្ទៃខាងក្រោយ (ឬ Custom /cancel):",
        "prompt_custom_color": "ផ្ញើពណ៌ hex ផ្ទាល់ខ្លួន (ឧ. #FF5722)។\nផ្ញើ /cancel ដើម្បីបោះបង់។",
        "prompt_logo": "ផ្ញើរូបថតសម្រាប់ឡូហ្គោហាង។\nផ្ញើ /cancel ដើម្បីបោះបង់។",
        "prompt_background_image": (
            "ផ្ញើរូបថតសម្រាប់ផ្ទៃខាងក្រោយហាង។\nផ្ញើ /cancel ដើម្បីបោះបង់។"
        ),
        "background_image_need_photo": (
            "សូមផ្ញើរូបថត (មិនមែនឯកសារ)។ ផ្ញើ /cancel ដើម្បីបោះបង់។"
        ),
        "background_image_uploaded": "បានផ្ទុករូបភាពផ្ទៃខាងក្រោយ។\nURL: {url}",
        "prompt_item_category": (
            "ផ្ញើឈ្មោះប្រភេទ (ឧ. Drinks, Food)។\nផ្ញើ /cancel ដើម្បីបោះបង់។"
        ),
        "prompt_item_name": (
            "ផ្ញើឈ្មោះមុខម្ហូបតាមទម្រង់:\nEnglish|Khmer|Chinese\n\n"
            "ឧទាហរណ៍:\nCoffee|កាហ្វេ|咖啡\n\nផ្ញើ /cancel ដើម្បីបោះបង់។"
        ),
        "prompt_item_price": "ផ្ញើតម្លៃជាលេខ (ឧ. 2.5)។\nផ្ញើ /cancel ដើម្បីបោះបង់។",
        "prompt_item_photo": (
            "ផ្ញើរូបថតស្រេចចិត្តសម្រាប់មុខម្ហូបនេះ ឬផ្ញើ /skip ដើម្បីរំលង។"
        ),
        "invalid_item_name": (
            "ទម្រង់មិនត្រឹមត្រូវ។ ផ្ញើត្រឹមត្រូវ:\nEnglish|Khmer|Chinese\n\n"
            "ឧទាហរណ៍:\nCoffee|កាហ្វេ|咖啡"
        ),
        "invalid_item_price": "តម្លៃមិនត្រឹមត្រូវ។ ផ្ញើលេខដូច 2.5:",
        "item_added": (
            "បានបន្ថែមមុខម្ហូប!\n\n"
            "ប្រភេទ: {category}\n"
            "ឈ្មោះ: {name}\n"
            "តម្លៃ: ${price:.2f}\n"
            "រូបភាព: {image}"
        ),
        "no_image": "(គ្មាន)",
        "btn_skip": "រំលងរូបថត",
        "invalid_shop_name": (
            "ទម្រង់មិនត្រឹមត្រូវ។ ផ្ញើត្រឹមត្រូវ:\nEnglish|Khmer|Chinese\n\n"
            "ឧទាហរណ៍:\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺"
        ),
        "invalid_color": "ពណ៌មិនត្រឹមត្រូវ។ ផ្ញើលេខ hex ដូច #FF5722:",
        "shop_names_updated": "បានធ្វើបច្ចុប្បន្នភាពឈ្មោះហាង។",
        "primary_updated": "បានធ្វើបច្ចុប្បន្នភាពពណ៌ចម្បងទៅ {value}។",
        "background_updated": "បានធ្វើបច្ចុប្បន្នភាពពណ៌ផ្ទៃខាងក្រោយទៅ {value}។",
        "logo_need_photo": "សូមផ្ញើរូបថត (មិនមែនឯកសារ)។ ផ្ញើ /cancel ដើម្បីបោះបង់។",
        "logo_uploaded": "បានផ្ទុកឡូហ្គោ។\nURL: {url}",
        "cancelled": "បានបោះបង់។ ផ្ញើ /settings ដើម្បីកែម្តងទៀត។",
        "preview_message": "មើលទុកជាមុន Mini App ហាងរបស់អ្នក:\n\n{link}",
        "btn_preview": "មើលទុកជាមុនហាង",
        "btn_deep_link": "បើកតំណភ្ជាប់",
        "btn_custom": "✏️ ផ្ទាល់ខ្លួន",
        "color_red": "ក្រហម",
        "color_orange": "ទឹកក្រូច",
        "color_yellow": "លឿង",
        "color_green": "បៃតង",
        "color_blue": "ខៀវ",
        "color_purple": "ស្វាយ",
        "color_black": "ខ្មៅ",
        "color_white": "ស",
        "customer_unknown": "មិនស្គាល់",
        "btn_confirm_payment": "បញ្ជាក់ការទូទាត់",
        "btn_cancel_order": "បោះបង់ការកម្មង់",
        "order_manage_header": "ការកម្មង់ {order_no}",
        "order_status": "ស្ថានភាព: {status}",
        "order_payment_confirmed": "បានបញ្ជាក់ការទូទាត់សម្រាប់ {order_no}។",
        "order_cancelled_msg": "បានបោះបង់ការកម្មង់ {order_no}។",
        "order_not_found": "រកមិនឃើញការកម្មង់ទេ។",
        "welcome_message": "សូមស្វាគមន៍! ចុចប៊ូតុងខាងក្រោមដើម្បីបើកម៉ឺនុយ។",
        "btn_open_menu": "បើកម៉ឺនុយ",
        "referral_saved": "បានភ្ជាប់ការណែនាំ! បញ្ចប់ការកម្មង់ដំបូងដើម្បីទទួលរង្វាន់។",
        "referral_self": "អ្នកមិនអាចប្រើតំណណែនាំផ្ទាល់ខ្លួនបានទេ។",
    },
    "zh": {
        "owner_only": "只有机器人所有者可以使用此命令。",
        "shop_not_found": "未找到店铺设置。",
        "settings_header": "店铺设置：",
        "not_set": "（未设置）",
        "label_en": "EN",
        "label_km": "KM",
        "label_zh": "ZH",
        "label_primary": "主题色",
        "label_background": "背景色",
        "label_logo": "Logo",
        "choose_option": "请选择下方选项（或发送 /cancel）：",
        "btn_shop_name": "设置店名（三语）",
        "btn_primary_color": "设置主题色",
        "btn_background_color": "设置背景色",
        "btn_upload_logo": "上传 Logo",
        "btn_upload_khqr": "上传 KHQR 收款码",
        "btn_background_image": "设置背景图片",
        "btn_add_item": "添加菜单项",
        "label_background_image": "背景图片",
        "label_khqr": "KHQR 收款码",
        "prompt_khqr": "请发送你的 KHQR 收款码图片。\n发送 /cancel 可取消。",
        "khqr_need_photo": "请发送图片（不要发送文件）。发送 /cancel 可取消。",
        "khqr_uploaded": "KHQR 收款码已上传。\nURL: {url}",
        "khqr_missing": "尚未上传 KHQR 收款码。请先打开 /settings 上传。",
        "btn_generate_payment": "生成付款页",
        "prompt_payment_amount": "请输入要收取的准确金额（美元）：\n发送 /cancel 可取消。",
        "invalid_payment_amount": "金额无效。请发送类似 2.50 的数字：",
        "payment_page_sent": "付款页已发送给顾客。",
        "payment_send_failed": "无法向顾客发送付款页。请确认对方已启动机器人。",
        "customer_id_missing": "此订单没有顾客 Telegram ID，无法发送付款信息。",
        "order_not_awaiting_payment": "订单 {order_no} 不在待付款状态（当前：{status}）。",
        "order_marked_paid": "订单 {order_no} 已标记为已付款。",
        "payment_amount_label": "收款金额：${amount:.2f}",
        "payment_transfer_text": "请向 {shop_name} 转账 ${amount:.2f}",
        "customer_order_paid": "您的订单 {order_no} 已付款。谢谢！",
        "customer_order_cancelled": "您的订单 {order_no} 已取消。",
        "prompt_shop_name": (
            "请按以下格式发送店名：\nEnglish|Khmer|Chinese\n\n"
            "示例：\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺\n\n发送 /cancel 可取消。"
        ),
        "choose_primary_color": "请选择主题色（或点自定义 /cancel）：",
        "choose_background_color": "请选择背景色（或点自定义 /cancel）：",
        "prompt_custom_color": "请发送自定义十六进制颜色（例如 #FF5722）。\n发送 /cancel 可取消。",
        "prompt_logo": "请发送一张图片作为店铺 Logo。\n发送 /cancel 可取消。",
        "prompt_background_image": "请发送一张图片作为店铺背景。\n发送 /cancel 可取消。",
        "background_image_need_photo": "请发送图片（不要发送文件）。发送 /cancel 可取消。",
        "background_image_uploaded": "背景图片已上传。\nURL: {url}",
        "prompt_item_category": "请发送分类名称（例如 Drinks、Food）。\n发送 /cancel 可取消。",
        "prompt_item_name": (
            "请按以下格式发送菜品名称：\nEnglish|Khmer|Chinese\n\n"
            "示例：\nCoffee|កាហ្វេ|咖啡\n\n发送 /cancel 可取消。"
        ),
        "prompt_item_price": "请发送价格数字（例如 2.5）。\n发送 /cancel 可取消。",
        "prompt_item_photo": "可发送菜品图片，或发送 /skip 跳过。",
        "invalid_item_name": (
            "格式无效。请严格按以下格式发送：\nEnglish|Khmer|Chinese\n\n"
            "示例：\nCoffee|កាហ្វេ|咖啡"
        ),
        "invalid_item_price": "价格无效。请发送类似 2.5 的数字：",
        "item_added": (
            "菜单项已添加！\n\n"
            "分类：{category}\n"
            "名称：{name}\n"
            "价格：${price:.2f}\n"
            "图片：{image}"
        ),
        "no_image": "（无）",
        "btn_skip": "跳过图片",
        "invalid_shop_name": (
            "格式无效。请严格按以下格式发送：\nEnglish|Khmer|Chinese\n\n"
            "示例：\nMy Shop|ហាងរបស់ខ្ញុំ|我的店铺"
        ),
        "invalid_color": "颜色格式无效。请发送类似 #FF5722 的十六进制颜色：",
        "shop_names_updated": "店名已更新。",
        "primary_updated": "主题色已更新为 {value}。",
        "background_updated": "背景色已更新为 {value}。",
        "logo_need_photo": "请发送图片（不要发送文件）。发送 /cancel 可取消。",
        "logo_uploaded": "Logo 已上传。\nURL: {url}",
        "cancelled": "已取消。发送 /settings 可再次编辑。",
        "preview_message": "预览你的店铺 Mini App：\n\n{link}",
        "btn_preview": "预览店铺",
        "btn_deep_link": "打开深度链接",
        "btn_custom": "✏️ 自定义",
        "color_red": "红色",
        "color_orange": "橙色",
        "color_yellow": "黄色",
        "color_green": "绿色",
        "color_blue": "蓝色",
        "color_purple": "紫色",
        "color_black": "黑色",
        "color_white": "白色",
        "customer_unknown": "未知",
        "btn_confirm_payment": "确认收款",
        "btn_cancel_order": "取消订单",
        "order_manage_header": "订单 {order_no}",
        "order_status": "状态：{status}",
        "order_payment_confirmed": "已确认订单 {order_no} 的收款。",
        "order_cancelled_msg": "订单 {order_no} 已取消。",
        "order_not_found": "未找到订单。",
        "welcome_message": "欢迎！点击下方按钮打开菜单。",
        "btn_open_menu": "打开菜单",
        "referral_saved": "推荐已绑定！完成首单即可获得奖励。",
        "referral_self": "不能使用自己的推荐链接。",
        "coupon_create_prompt_type": "创建优惠券 — 请选择类型：",
        "btn_coupon_fixed": "固定金额 $",
        "btn_coupon_percent": "百分比 %",
        "coupon_prompt_value_fixed": "请发送固定优惠金额（美元，例如 2.5）：",
        "coupon_prompt_value_percent": "请发送折扣百分比（例如 10 表示 10%）：",
        "coupon_prompt_min_order": "请发送最低订单金额（美元，0 表示无限制）：",
        "coupon_prompt_usage_limit": "请发送使用次数上限（例如 50）：",
        "coupon_prompt_expiry": "请发送有效天数（从今天起，0 = 永不过期）：",
        "coupon_invalid_number": "数字无效，请重试：",
        "coupon_created": (
            "优惠券已创建！\n\n"
            "代码：{code}\n"
            "类型：{type}\n"
            "面值：{value}\n"
            "最低消费：${min_order:.2f}\n"
            "使用上限：{usage_limit}\n"
            "到期：{expires}"
        ),
        "coupon_no_expiry": "永不过期",
        "mycoupons_empty": "你没有未使用的优惠券。",
        "mycoupons_header": "你的未使用优惠券：",
        "mycoupons_line_fixed": "• {code}：减 ${value:.2f}（满 ${min_order:.2f}）{expires}",
        "mycoupons_line_percent": "• {code}：{value:.0f}% 折扣（满 ${min_order:.2f}）{expires}",
        "mycoupons_expires": " — {date} 到期",
        "welcome_coupon_granted": "礼物：优惠券 {code}（减 ${value:.2f}）已到账！发送 /mycoupons 查看",
        "referral_reward_granted": "推荐奖励：优惠券 {code}（减 ${value:.2f}）！发送 /mycoupons 查看",
        "review_invite": "为餐点评分，赚取积分！",
        "btn_leave_review": "去评价",
        "reviews_empty": "暂无评价。",
        "reviews_header": "最近评价：",
        "review_line": "#{id} ⭐{rating}/5 — {name}\n{comment}",
        "btn_feature_review": "精选",
        "btn_delete_review": "删除",
        "review_featured": "评价 #{id} 已设为精选。",
        "review_deleted": "评价 #{id} 已删除。",
        "review_not_found": "未找到评价。",
        "tiktok_owner_notify": (
            "新的 TikTok 投稿 #{id}\n"
            "用户：{user_id}\n"
            "订单：{order_no}\n"
            "视频：{url}"
        ),
        "btn_approve_tiktok": "通过",
        "btn_reject_tiktok": "拒绝",
        "tiktok_approved": "TikTok #{id} 已通过，优惠券已发给顾客。",
        "tiktok_rejected": "TikTok #{id} 已拒绝。",
        "tiktok_already_handled": "该投稿已处理过。",
        "tiktok_reward_user": "你的 TikTok 已通过！优惠券 {code}（减 $5）。发送 /mycoupons 查看",
        "tiktok_reject_user": "你的 TikTok 投稿未通过。",
        "poster_choose_type": "请选择海报类型：",
        "btn_poster_table_qr": "桌码 QR",
        "btn_poster_promotion": "促销海报",
        "poster_prompt_promo_text": "请发送海报上的促销文案。\n发送 /cancel 可取消。",
        "poster_prompt_bg": "可发送背景图，或发送 /skip 使用纯色背景。",
        "poster_ready": "海报已生成。",
        "poster_failed": "海报生成失败。",
        "poster_need_bot_username": "无法获取机器人用户名，请稍后重试。",
        "poster_khqr_missing": "请先在 /settings 上传 KHQR 收款码。",
        "prompt_item_vegetarian": "这是素食吗？请回复 yes 或 no。\n发送 /cancel 可取消。",
        "invalid_item_vegetarian": "请回复 yes 或 no：",
        "festival_list_header": "节日列表（点击激活）：",
        "festival_line": "{name}\n{start} → {end} · 优惠 {discount}%{veg}",
        "festival_veg_tag": " · 素食主题",
        "btn_activate_festival": "激活",
        "btn_clear_festival": "清除当前节日",
        "festival_activated": "已激活：{name}（优惠 {discount}%）",
        "festival_cleared": "已关闭节日活动。",
        "festival_none": "尚未配置节日。",
        "festival_active_label": "当前激活：{name}",
        "festival_not_active": "当前没有激活的节日。",
        "btn_group_invite": "设置社群邀请链接",
        "label_group_invite": "社群邀请链接",
        "prompt_group_invite": (
            "请发送 Telegram 群邀请链接（https://t.me/+...）。\n"
            "发送 /cancel 可取消。"
        ),
        "invalid_group_invite": "请发送有效的 https://t.me/ 链接：",
        "group_invite_saved": "社群邀请链接已保存。",
        "queue_empty": "当前没有排队。",
        "queue_header": "当前排队：",
        "queue_line": "#{number} · {size} 人 · {status} · 用户 {user_id}",
        "btn_queue_next": "下一位",
        "btn_queue_call": "叫号 #{number}",
        "queue_advanced": "已将 #{number} 设为点餐中。通知顾客：{notified}",
        "queue_called": "已叫号 #{number}（就绪）。通知顾客：{notified}",
        "queue_no_waiting": "没有等待中的客人。",
        "queue_notify_ordering": "轮到你了！排队号 #{number}。可在小程序预点餐。",
        "queue_notify_ready": "请入座/到柜台！排队号 #{number}。",
        "queue_notify_failed": "否（请客人先 /start 机器人）",
        "queue_notify_ok": "是",
        "stats_header": "数据（{period}）：",
        "stats_orders": "订单数：{count}",
        "stats_revenue": "营收：${revenue:.2f}",
        "stats_top_items": "热销：",
        "stats_item_line": "• {name} × {qty}",
        "stats_no_items": "（无）",
        "export_prompt_start": "导出 CSV — 请发送开始日期（YYYY-MM-DD）：",
        "export_prompt_end": "请发送结束日期（YYYY-MM-DD）：",
        "export_invalid_date": "日期无效。请使用 YYYY-MM-DD：",
        "export_empty": "该日期范围内没有订单。",
        "export_ready": "订单导出 {start} → {end}",
        "export_usage": "用法：/export YYYY-MM-DD YYYY-MM-DD\n或发送 /export 按提示操作。",
    },
}

# Multilingual strings for order notifications to the shop owner
ORDER_TRANSLATIONS = {
    "en": {
        "new_order_title": "New Order {order_no}",
        "items_label": "Items:",
        "total_label": "Total: ${total:.2f}",
        "customer_label": "Customer: {customer}",
        "manage_order_button": "Manage Order",
        "order_number_prefix": "#",
        "customer_unknown": "Unknown",
    },
    "km": {
        "new_order_title": "ការកម្មង់ថ្មី {order_no}",
        "items_label": "ទំនិញ:",
        "total_label": "សរុប: ${total:.2f}",
        "customer_label": "អតិថិជន: {customer}",
        "manage_order_button": "គ្រប់គ្រងការកម្មង់",
        "order_number_prefix": "#",
        "customer_unknown": "មិនស្គាល់",
    },
    "zh": {
        "new_order_title": "新订单 {order_no}",
        "items_label": "商品：",
        "total_label": "合计：${total:.2f}",
        "customer_label": "顾客：{customer}",
        "manage_order_button": "管理订单",
        "order_number_prefix": "#",
        "customer_unknown": "未知",
    },
}

OWNER_LANG_FILE = os.path.join(os.path.dirname(__file__), "owner_lang.txt")
_owner_lang: str = "en"

flask_app = Flask(__name__, static_folder="webapp", static_url_path="/webapp")
database.init_db()
_migrated = database.migrate_legacy_public_urls(BASE_URL, LEGACY_PUBLIC_HOSTS)
if _migrated:
    logger.info("Migrated %s legacy public URL(s) to BASE_URL=%s", _migrated, BASE_URL)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(BG_DIR, exist_ok=True)
os.makedirs(MENU_DIR, exist_ok=True)
os.makedirs(KHQR_DIR, exist_ok=True)
os.makedirs(PAYMENTS_DIR, exist_ok=True)
os.makedirs(REVIEWS_DIR, exist_ok=True)
os.makedirs(POSTERS_DIR, exist_ok=True)


def configure_telegram_webapp() -> None:
    """Point Telegram Menu Button / Mini App at the current BASE_URL."""
    if not BASE_URL:
        logger.error("BASE_URL is empty; Mini App buttons will not work")
        return
    if not BASE_URL.startswith("https://"):
        logger.error("BASE_URL must be https:// for Telegram Mini Apps: %s", BASE_URL)
        return

    webapp_url = f"{BASE_URL}/webapp/index.html"
    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    try:
        requests.post(
            f"{api}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=20,
        )
        resp = requests.post(
            f"{api}/setChatMenuButton",
            json={
                "menu_button": {
                    "type": "web_app",
                    "text": "Open Menu",
                    "web_app": {"url": webapp_url},
                }
            },
            timeout=20,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Telegram menu button set to %s", webapp_url)
        else:
            logger.error("setChatMenuButton failed: %s", data)
    except Exception:
        logger.exception("Failed to configure Telegram Mini App menu button")


def detect_lang_code(language_code: str | None) -> str:
    code = (language_code or "").lower()
    if code.startswith("km"):
        return "km"
    if code.startswith("zh"):
        return "zh"
    return "en"


def detect_lang(update: Update) -> str:
    code = ""
    if update.effective_user and update.effective_user.language_code:
        code = update.effective_user.language_code
    return detect_lang_code(code)


def save_owner_lang(lang: str) -> None:
    global _owner_lang
    if lang not in ORDER_TRANSLATIONS:
        lang = "en"
    _owner_lang = lang
    try:
        with open(OWNER_LANG_FILE, "w", encoding="utf-8") as lang_file:
            lang_file.write(lang)
    except OSError:
        logger.exception("Failed to save owner language")


def load_owner_lang_from_file() -> str:
    try:
        if os.path.exists(OWNER_LANG_FILE):
            with open(OWNER_LANG_FILE, encoding="utf-8-sig") as lang_file:
                lang = lang_file.read().strip().lower()
            if lang in ORDER_TRANSLATIONS:
                return lang
    except OSError:
        logger.exception("Failed to read owner language")
    return "en"


def get_owner_lang() -> str:
    """Return the shop owner's preferred language (km/zh/en)."""
    global _owner_lang
    if _owner_lang in ORDER_TRANSLATIONS:
        return _owner_lang
    _owner_lang = load_owner_lang_from_file()
    return _owner_lang


# Load persisted owner language at startup
_owner_lang = load_owner_lang_from_file()


def remember_owner_language(update: Update) -> None:
    """When OWNER_ID sends any update, store their Telegram language_code."""
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return
    lang = detect_lang_code(user.language_code)
    save_owner_lang(lang)
    logger.info("Owner language updated to %s (from language_code=%s)", lang, user.language_code)


def get_lang(update: Update, context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    # Always refresh owner's language from Telegram language_code
    remember_owner_language(update)

    if context is not None:
        # Prefer freshly detected language for owners; otherwise cache per user
        if update.effective_user and update.effective_user.id == OWNER_ID:
            lang = detect_lang(update)
            context.user_data["lang"] = lang
            return lang

        stored = context.user_data.get("lang")
        if stored in BOT_TRANSLATIONS:
            return stored
        lang = detect_lang(update)
        context.user_data["lang"] = lang
        return lang

    return detect_lang(update)


def t(lang: str, key: str, **kwargs) -> str:
    text = BOT_TRANSLATIONS.get(lang, BOT_TRANSLATIONS["en"]).get(key)
    if text is None:
        text = BOT_TRANSLATIONS["en"].get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def ot(lang: str, key: str, **kwargs) -> str:
    """Translate order-notification strings for the shop owner."""
    text = ORDER_TRANSLATIONS.get(lang, ORDER_TRANSLATIONS["en"]).get(key)
    if text is None:
        text = ORDER_TRANSLATIONS["en"].get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure_single_instance() -> None:
    if is_port_in_use(FLASK_PORT):
        print("Bot already running")
        sys.exit(1)


def is_owner(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == OWNER_ID


def settings_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "btn_shop_name"), callback_data="set_shop_name")],
            [InlineKeyboardButton(t(lang, "btn_primary_color"), callback_data="set_primary_color")],
            [
                InlineKeyboardButton(
                    t(lang, "btn_background_color"),
                    callback_data="set_background_color",
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "btn_background_image"),
                    callback_data="set_background_image",
                )
            ],
            [InlineKeyboardButton(t(lang, "btn_add_item"), callback_data="add_menu_item")],
            [InlineKeyboardButton(t(lang, "btn_upload_logo"), callback_data="upload_logo")],
            [InlineKeyboardButton(t(lang, "btn_upload_khqr"), callback_data="upload_khqr")],
            [
                InlineKeyboardButton(
                    t(lang, "btn_group_invite"),
                    callback_data="set_group_invite",
                )
            ],
        ]
    )


def color_picker_keyboard(lang: str, field: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for color_key, emoji, hex_value in PRESET_COLORS:
        label = f"{emoji} {t(lang, f'color_{color_key}')}"
        row.append(
            InlineKeyboardButton(label, callback_data=f"pick_color:{field}:{hex_value}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(t(lang, "btn_custom"), callback_data=f"custom_color:{field}")]
    )
    return InlineKeyboardMarkup(rows)


def format_settings_message(shop: dict, lang: str) -> str:
    not_set = t(lang, "not_set")
    return (
        f"{t(lang, 'settings_header')}\n\n"
        f"{t(lang, 'label_en')}: {shop.get('name_en') or not_set}\n"
        f"{t(lang, 'label_km')}: {shop.get('name_km') or not_set}\n"
        f"{t(lang, 'label_zh')}: {shop.get('name_zh') or not_set}\n"
        f"{t(lang, 'label_primary')}: {shop.get('primary_color') or not_set}\n"
        f"{t(lang, 'label_background')}: {shop.get('background_color') or not_set}\n"
        f"{t(lang, 'label_logo')}: {shop.get('logo_url') or not_set}\n"
        f"{t(lang, 'label_background_image')}: {shop.get('background_image_url') or not_set}\n"
        f"{t(lang, 'label_khqr')}: {shop.get('khqr_url') or not_set}\n"
        f"{t(lang, 'label_group_invite')}: {shop.get('group_invite_link') or not_set}\n\n"
        f"{t(lang, 'choose_option')}"
    )


async def save_color_and_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
    value: str,
) -> int:
    lang = get_lang(update, context)
    value = value.upper()
    database.update_shop_settings(SHOP_ID, **{field: value})
    shop = database.get_shop_settings(SHOP_ID)
    confirm_key = "primary_updated" if field == "primary_color" else "background_updated"
    message = update.effective_message
    text = f"{t(lang, confirm_key, value=value)}\n\n{format_settings_message(shop, lang)}"
    if message:
        await message.reply_text(text, reply_markup=settings_keyboard(lang))
    context.user_data.pop("color_field", None)
    return ConversationHandler.END


@flask_app.route("/webapp/<path:filename>")
def serve_webapp(filename):
    return send_from_directory("webapp", filename)


@flask_app.route("/static/<path:filename>")
def serve_static(filename):
    # Prefer webapp/static (backgrounds), then project static/ (logo)
    webapp_static = os.path.join(os.path.dirname(__file__), "webapp", "static")
    webapp_candidate = os.path.join(webapp_static, filename)
    if os.path.isfile(webapp_candidate):
        return send_from_directory(webapp_static, filename)
    return send_from_directory(STATIC_DIR, filename)


def public_url(path: str) -> str:
    """Build an absolute public URL from a path using BASE_URL."""
    if not path:
        return BASE_URL
    if path.startswith("http://") or path.startswith("https://"):
        for marker in ("/static/", "/webapp/"):
            idx = path.find(marker)
            if idx >= 0:
                path = path[idx:]
                break
        else:
            return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{BASE_URL}{path}" if BASE_URL else path


def absolutize_media_url(url: str | None) -> str | None:
    """Rewrite stored media URLs so they use the current BASE_URL."""
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    return public_url(url)


@flask_app.route("/api/shop/<int:shop_id>")
def get_shop(shop_id):
    shop = database.get_shop_settings(shop_id)
    if not shop:
        return jsonify({"error": "Shop not found"}), 404
    return jsonify(
        {
            "id": shop["id"],
            "name_en": shop.get("name_en"),
            "name_km": shop.get("name_km"),
            "name_zh": shop.get("name_zh"),
            "logo_url": absolutize_media_url(shop.get("logo_url")),
            "primary_color": shop.get("primary_color"),
            "background_color": shop.get("background_color"),
            "background_image_url": absolutize_media_url(
                shop.get("background_image_url")
            ),
            "group_invite_link": shop.get("group_invite_link"),
        }
    )


def localize_category(category: str) -> dict:
    key = (category or "").strip().lower()
    if key in CATEGORY_I18N:
        return dict(CATEGORY_I18N[key])
    label = (category or "").strip() or "Other"
    return {"en": label, "km": label, "zh": label}


@flask_app.route("/api/menu/<int:shop_id>")
def get_menu(shop_id):
    items = database.get_menu_items(shop_id)
    festival = database.get_active_festival(shop_id)
    grouped: OrderedDict[str, list] = OrderedDict()
    for item in items:
        category = item.get("category") or "Other"
        grouped.setdefault(category, []).append(
            {
                "id": item["id"],
                "name_en": item.get("name_en"),
                "name_km": item.get("name_km"),
                "name_zh": item.get("name_zh"),
                "price": item.get("price"),
                "image_url": absolutize_media_url(item.get("image_url")),
                "is_vegetarian": int(item.get("is_vegetarian") or 0),
            }
        )

    categories = [
        {
            "name": localize_category(category),
            "items": category_items,
        }
        for category, category_items in grouped.items()
    ]
    payload = {"categories": categories}
    if festival:
        festival_name = {
            "en": festival.get("name_en") or "",
            "km": festival.get("name_km") or festival.get("name_en") or "",
            "zh": festival.get("name_zh") or festival.get("name_en") or "",
        }
        payload.update(
            {
                "festival_discount": float(festival.get("discount_percent") or 0),
                "festival_name": festival_name,
                "festival_is_vegetarian": int(festival.get("is_vegetarian") or 0),
                "festival": {
                    "id": festival["id"],
                    "name_en": festival_name["en"],
                    "name_km": festival_name["km"],
                    "name_zh": festival_name["zh"],
                    "discount_percent": float(festival.get("discount_percent") or 0),
                    "is_vegetarian": int(festival.get("is_vegetarian") or 0),
                    "start_date": festival.get("start_date"),
                    "end_date": festival.get("end_date"),
                },
            }
        )
    else:
        payload.update(
            {
                "festival_discount": 0,
                "festival_name": None,
                "festival_is_vegetarian": 0,
                "festival": None,
            }
        )
    return jsonify(payload)


def owner_lang_default() -> str:
    return get_owner_lang()


def format_item_line(item: dict, lang: str = "en") -> str:
    """Keep trilingual names visible in the items list."""
    qty = item.get("quantity") or item.get("qty") or 1
    name_en = item.get("name_en") or ""
    name_km = item.get("name_km") or ""
    name_zh = item.get("name_zh") or ""
    return f"- {qty}x {name_en} / {name_km} / {name_zh}"


def shop_name_for_lang(shop: dict | None, lang: str) -> str:
    if not shop:
        return "Shop"
    key = f"name_{lang}" if lang in ("en", "km", "zh") else "name_en"
    return shop.get(key) or shop.get("name_en") or "Shop"


def local_path_from_public_url(url: str | None) -> str | None:
    """Map a BASE_URL /static/... path to a local webapp/static or static/ file."""
    if not url:
        return None
    marker = "/static/"
    idx = url.find(marker)
    if idx < 0:
        return None
    rel = url[idx + len(marker) :].lstrip("/").replace("/", os.sep)
    candidate = os.path.join(os.path.dirname(__file__), "webapp", "static", rel)
    if os.path.isfile(candidate):
        return candidate
    fallback = os.path.join(STATIC_DIR, rel)
    if os.path.isfile(fallback):
        return fallback
    return None


def _is_latin_run_char(ch: str) -> bool:
    """Latin letters, digits, and common currency/punctuation used in amounts."""
    if ch.isspace():
        return True
    code = ord(ch)
    if code < 128:
        return True
    return ch in "$€£¥₩₽"


def split_script_runs(text: str) -> list[tuple[str, str]]:
    """Split text into ('latin'|'script') runs for multi-font drawing."""
    if not text:
        return []
    runs: list[tuple[str, str]] = []
    buf = text[0]
    latin = _is_latin_run_char(text[0]) and not text[0].isspace()
    # Leading spaces inherit the next real char's script; treat as latin for sizing
    if text[0].isspace():
        latin = True

    for ch in text[1:]:
        ch_latin = _is_latin_run_char(ch)
        # Spaces stay in the current run
        if ch.isspace() or ch_latin == latin or (ch.isspace()):
            buf += ch
            continue
        runs.append((buf, "latin" if latin else "script"))
        buf = ch
        latin = ch_latin
    runs.append((buf, "latin" if latin else "script"))
    return runs


def resolve_font_path(lang: str, kind: str = "script") -> str | None:
    """Return best available font path for a language/script kind."""
    lang = lang if lang in FONT_FILES else "en"
    if kind == "latin" or lang == "en":
        candidates = [
            os.path.join(FONTS_DIR, DEFAULT_PROJECT_FONT),
            os.path.join(FONTS_DIR, FONT_FILES["en"]),
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]
    elif lang == "zh":
        candidates = [
            os.path.join(FONTS_DIR, FONT_FILES["zh"]),
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
    elif lang == "km":
        candidates = [
            r"C:\Windows\Fonts\LeelawUI.ttf",
            r"C:\Windows\Fonts\LeelawUIb.ttf",
            os.path.join(FONTS_DIR, FONT_FILES["km"]),
        ]
    else:
        candidates = [os.path.join(FONTS_DIR, DEFAULT_PROJECT_FONT)]

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def load_truetype(path: str | None, size: int) -> ImageFont.ImageFont | None:
    if not path:
        return None
    try:
        return ImageFont.truetype(path, size)
    except OSError as exc:
        logger.warning("Failed to load font %s: %s", path, exc)
        return None


def load_image_font(
    size: int = 40,
    lang: str = "en",
    text: str | None = None,
) -> tuple[ImageFont.ImageFont, bool]:
    """
    Load a TrueType font for the customer's language.
    Returns (font, is_truetype). is_truetype=False means Pillow default (Latin-only).
    """
    lang = lang if lang in FONT_FILES else "en"
    path = resolve_font_path(lang, "script" if lang != "en" else "latin")
    font = load_truetype(path, size)
    if font is not None:
        return font, True

    # Fall back to project Noto Sans, then Pillow default
    font = load_truetype(resolve_font_path("en", "latin"), size)
    if font is not None:
        return font, True

    logger.warning(
        "No TrueType font found for lang=%s; falling back to Pillow default (English-only).",
        lang,
    )
    return ImageFont.load_default(), False


def measure_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    lang: str,
    font_size: int,
) -> tuple[int, int, list[tuple[str, ImageFont.ImageFont]]]:
    """Measure width/height of mixed-script text and return per-run fonts."""
    script_path = resolve_font_path(lang, "script")
    latin_path = resolve_font_path("en", "latin")
    latin_font = load_truetype(latin_path, font_size) or ImageFont.load_default()
    script_font = load_truetype(script_path, font_size) or latin_font

    # Fonts like Leelawadee UI cover Khmer + Latin — draw as one run (better shaping)
    basename = os.path.basename(script_path or "").lower()
    if lang in ("km", "zh") and any(token in basename for token in ("leelaw", "msyh", "simhei", "simsun")):
        bbox = draw.textbbox((0, 0), text, font=script_font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1], [(text, script_font)]

    runs_with_fonts: list[tuple[str, ImageFont.ImageFont]] = []
    total_w = 0
    max_h = 0
    for chunk, kind in split_script_runs(text):
        font = latin_font if kind == "latin" else script_font
        runs_with_fonts.append((chunk, font))
        bbox = draw.textbbox((0, 0), chunk, font=font)
        total_w += bbox[2] - bbox[0]
        max_h = max(max_h, bbox[3] - bbox[1])
    return total_w, max_h, runs_with_fonts


def draw_mixed_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    runs: list[tuple[str, ImageFont.ImageFont]],
    fill: tuple[int, int, int, int],
) -> None:
    cursor_x = x
    for chunk, font in runs:
        draw.text((cursor_x, y), chunk, font=font, fill=fill)
        bbox = draw.textbbox((cursor_x, y), chunk, font=font)
        cursor_x = bbox[2]


def render_text_banner_windows(
    text: str,
    width: int,
    font_size: int = 40,
    font_name: str = "Leelawadee UI",
) -> Image.Image | None:
    """
    Render a text banner with Windows GDI+ (correct Khmer shaping).
    Returns an RGBA image, or None if unavailable.
    """
    if sys.platform != "win32":
        return None

    import subprocess
    import tempfile

    ps_script = """
param(
    [Parameter(Mandatory=$true)][string]$Text,
    [Parameter(Mandatory=$true)][int]$Width,
    [Parameter(Mandatory=$true)][int]$FontSize,
    [Parameter(Mandatory=$true)][string]$FontName,
    [Parameter(Mandatory=$true)][string]$OutPath
)
Add-Type -AssemblyName System.Drawing
$font = New-Object System.Drawing.Font($FontName, $FontSize, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$probe = New-Object System.Drawing.Bitmap(8, 8)
$g = [System.Drawing.Graphics]::FromImage($probe)
$size = $g.MeasureString($Text, $font)
$g.Dispose(); $probe.Dispose()
$bannerH = [Math]::Max(90, [int][Math]::Ceiling($size.Height) + 36)
$bmp = New-Object System.Drawing.Bitmap($Width, $bannerH)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$gfx.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$gfx.Clear([System.Drawing.Color]::FromArgb(170, 0, 0, 0))
$white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$black = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::Black)
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
$rect = New-Object System.Drawing.RectangleF(0, 0, $Width, $bannerH)
foreach ($dx in -2,-1,0,1,2) {
  foreach ($dy in -2,-1,0,1,2) {
    if ($dx -eq 0 -and $dy -eq 0) { continue }
    $r = New-Object System.Drawing.RectangleF($dx, $dy, $Width, $bannerH)
    $gfx.DrawString($Text, $font, $black, $r, $format)
  }
}
$gfx.DrawString($Text, $font, $white, $rect, $format)
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose(); $font.Dispose(); $white.Dispose(); $black.Dispose()
"""

    out_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    out_path = out_tmp.name
    out_tmp.close()
    ps1_tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", delete=False, mode="w", encoding="utf-8-sig"
    )
    ps1_path = ps1_tmp.name
    ps1_tmp.write(ps_script)
    ps1_tmp.close()

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                ps1_path,
                "-Text",
                text,
                "-Width",
                str(width),
                "-FontSize",
                str(font_size),
                "-FontName",
                font_name,
                "-OutPath",
                out_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            logger.warning(
                "Windows GDI text render failed: %s",
                (completed.stderr or completed.stdout or "").strip()[:300],
            )
            return None
        img = Image.open(out_path).convert("RGBA")
        img.load()
        return img
    except Exception:
        logger.exception("Windows GDI text render raised")
        return None
    finally:
        for path in (out_path, ps1_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def generate_payment_image(
    khqr_path: str,
    output_path: str,
    amount: float,
    shop_name: str,
    customer_lang: str = "en",
) -> str:
    """
    Overlay transfer instructions on the KHQR image and save JPEG.
    Text is rendered in the customer's language when suitable fonts are available.
    Latin digits/$ are always drawn with NotoSans so Khmer/CJK fonts without those
    glyphs do not produce tofu boxes. Falls back to English if fonts are missing.
    """
    cust_lang = detect_lang_code(customer_lang)
    banner_text = t(cust_lang, "payment_transfer_text", amount=amount, shop_name=shop_name)

    script_path = resolve_font_path(cust_lang, "script")
    latin_path = resolve_font_path("en", "latin")

    # No usable TrueType → English + default font
    if not latin_path and not script_path:
        logger.warning("Font loading failed; using English text with Pillow default font.")
        cust_lang = "en"
        banner_text = t("en", "payment_transfer_text", amount=amount, shop_name=shop_name)
    elif cust_lang != "en" and not script_path:
        logger.warning(
            "No font for lang=%s; falling back to English payment text.",
            cust_lang,
        )
        cust_lang = "en"
        banner_text = t("en", "payment_transfer_text", amount=amount, shop_name=shop_name)

    base = Image.open(khqr_path).convert("RGBA")
    width, _height = base.size

    # Prefer Windows GDI for Khmer (correct OpenType shaping; avoids dotted circles)
    if cust_lang == "km":
        gdi_banner = render_text_banner_windows(banner_text, width, font_size=36)
        if gdi_banner is not None:
            composed = base.copy()
            composed.paste(gdi_banner, (0, 0), gdi_banner)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            composed.convert("RGB").save(output_path, format="JPEG", quality=92)
            return output_path

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = 40
    padding_x = 24
    padding_y = 18

    text_w, text_h, runs = measure_mixed_text(draw, banner_text, cust_lang, font_size)
    while text_w > width - padding_x * 2 and font_size > 22:
        font_size -= 2
        text_w, text_h, runs = measure_mixed_text(draw, banner_text, cust_lang, font_size)

    banner_h = max(90, text_h + padding_y * 2)

    # Semi-transparent black rectangle behind text for readability
    draw.rectangle((0, 0, width, banner_h), fill=(0, 0, 0, 170))

    x = max(padding_x, (width - text_w) // 2)
    y = max(padding_y, (banner_h - text_h) // 2)

    # Black outline then white fill (run-based so each script uses the right font)
    outline = 2
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx == 0 and dy == 0:
                continue
            draw_mixed_text(draw, x + dx, y + dy, runs, (0, 0, 0, 255))
    draw_mixed_text(draw, x, y, runs, (255, 255, 255, 255))

    composed = Image.alpha_composite(base, overlay).convert("RGB")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    composed.save(output_path, format="JPEG", quality=92)
    return output_path


def format_order_number(order_id: int, lang: str | None = None) -> str:
    lang = lang or get_owner_lang()
    prefix = ot(lang, "order_number_prefix")
    return f"{prefix}{order_id + 1000}"


def notify_owner_new_order(order: dict, lang: str | None = None) -> None:
    lang = lang or get_owner_lang()
    order_no = format_order_number(order["id"], lang)
    try:
        items = json.loads(order.get("items") or "[]")
    except json.JSONDecodeError:
        items = []

    lines = [
        ot(lang, "new_order_title", order_no=order_no),
        "",
        ot(lang, "items_label"),
    ]
    for item in items:
        lines.append(format_item_line(item, lang))
    lines.append("")
    lines.append(ot(lang, "total_label", total=float(order.get("total") or 0)))
    customer = order.get("customer_name") or ot(lang, "customer_unknown")
    lines.append(ot(lang, "customer_label", customer=customer))

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": ot(lang, "manage_order_button"),
                    "callback_data": f"manage_order_{order['id']}",
                }
            ]
        ]
    }

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": OWNER_ID,
                "text": "\n".join(lines),
                "reply_markup": keyboard,
            },
            timeout=15,
        )
    except Exception:
        logger.exception("Failed to notify owner about order %s", order.get("id"))


@flask_app.route("/api/order", methods=["POST"])
def create_order_api():
    data = request.get_json(silent=True) or {}
    shop_id = int(data.get("shop_id") or SHOP_ID)
    items = data.get("items") or []
    total = float(data.get("total") or 0)
    language = detect_lang_code(data.get("language") or "en")
    coupon_code = (data.get("coupon_code") or "").strip().upper() or None

    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "Cart is empty"}), 400

    customer_id = data.get("customer_id")
    customer_name = data.get("customer_name")

    user = data.get("user") or {}
    if isinstance(user, dict):
        customer_id = customer_id or user.get("id")
        if not customer_name:
            parts = [user.get("first_name") or "", user.get("last_name") or ""]
            customer_name = " ".join(part for part in parts if part).strip() or user.get(
                "username"
            )

    discount_amount = 0.0
    if coupon_code and customer_id:
        result = database.validate_coupon(coupon_code, int(customer_id), total, shop_id)
        if not result.get("valid"):
            return jsonify(
                {"ok": False, "error": "Invalid coupon", "reason": result.get("reason")}
            ), 400
        discount_amount = float(result.get("discount") or 0)
        database.mark_coupon_used(coupon_code, int(customer_id))

    order_total = max(0.0, total - discount_amount)
    order_type = (data.get("order_type") or "takeaway").strip().lower()
    queue_id = data.get("queue_id")
    try:
        queue_id = int(queue_id) if queue_id is not None else None
    except (TypeError, ValueError):
        queue_id = None

    status = "pending"
    if order_type == "dinein" and queue_id:
        status = "pending_preorder"
        order_type = "dinein"
    elif order_type not in ("takeaway", "dinein"):
        order_type = "takeaway"

    order = database.create_order(
        shop_id=shop_id,
        items_json=json.dumps(items, ensure_ascii=False),
        total=order_total,
        customer_id=int(customer_id) if customer_id else None,
        customer_name=customer_name,
        customer_language=language,
        coupon_code=coupon_code,
        discount_amount=discount_amount,
        order_type=order_type,
        queue_id=queue_id,
        status=status,
    )

    if customer_id:
        first = None
        if isinstance(user, dict):
            first = user.get("first_name")
        database.ensure_customer(int(customer_id), first_name=first or customer_name)

    notify_owner_new_order(order)

    return jsonify(
        {
            "ok": True,
            "order_id": order["id"],
            "order_number": database.order_number(order["id"]),
            "status": order.get("status"),
            "language": language,
            "discount": discount_amount,
            "total": order_total,
            "coupon_code": coupon_code,
            "order_type": order.get("order_type"),
            "queue_id": order.get("queue_id"),
        }
    )


@flask_app.route("/api/queue/join", methods=["POST"])
def queue_join_api():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    party_size = data.get("party_size") or 1
    shop_id = int(data.get("shop_id") or SHOP_ID)
    if not user_id:
        return jsonify({"ok": False, "error": "missing_user"}), 400
    try:
        user_id = int(user_id)
        party_size = int(party_size)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_params"}), 400

    entry = database.join_queue(shop_id, user_id, party_size)
    return jsonify(
        {
            "ok": True,
            "queue_id": entry["id"],
            "queue_number": entry["queue_number"],
            "party_size": entry["party_size"],
            "status": entry["status"],
            "estimated_wait": entry.get("estimated_wait", 0),
            "already_in_queue": bool(entry.get("already_in_queue")),
            "start_bot_hint": True,
        }
    )


@flask_app.route("/api/queue/status", methods=["GET"])
def queue_status_api():
    user_id = request.args.get("user_id")
    shop_id = int(request.args.get("shop_id") or SHOP_ID)
    if not user_id:
        return jsonify({"ok": False, "error": "missing_user"}), 400
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_user"}), 400

    entry = database.get_active_queue_for_user(shop_id, user_id)
    if not entry:
        return jsonify({"ok": True, "in_queue": False, "entry": None})
    wait = database.estimate_queue_wait(shop_id, int(entry["queue_number"]))
    return jsonify(
        {
            "ok": True,
            "in_queue": True,
            "entry": {
                "queue_id": entry["id"],
                "queue_number": entry["queue_number"],
                "party_size": entry["party_size"],
                "status": entry["status"],
                "estimated_wait": wait,
            },
        }
    )


@flask_app.route("/api/stats", methods=["GET"])
def stats_api():
    # Optional helper for Mini App; bot commands are primary dashboard.
    period = (request.args.get("period") or "today").lower()
    if period not in ("today", "week"):
        period = "today"
    owner_id = request.args.get("owner_id")
    try:
        if int(owner_id) != OWNER_ID:
            return jsonify({"ok": False, "error": "forbidden"}), 403
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    stats = database.get_order_stats(SHOP_ID, period)
    return jsonify({"ok": True, **stats})


@flask_app.route("/api/validate_coupon", methods=["GET"])
def validate_coupon_api():
    code = request.args.get("code") or ""
    user_id = request.args.get("user_id")
    total = request.args.get("total") or "0"
    shop_id = int(request.args.get("shop_id") or SHOP_ID)
    if not code or not user_id:
        return jsonify({"valid": False, "discount": 0, "reason": "missing_params"}), 400
    try:
        result = database.validate_coupon(code, int(user_id), float(total), shop_id)
    except (TypeError, ValueError):
        return jsonify({"valid": False, "discount": 0, "reason": "bad_params"}), 400
    return jsonify(result)


@flask_app.route("/api/mycoupons", methods=["GET"])
def mycoupons_api():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "coupons": [], "error": "missing user_id"}), 400
    try:
        coupons = database.get_user_unused_coupons(int(user_id))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "coupons": [], "error": "bad user_id"}), 400
    return jsonify({"ok": True, "coupons": coupons})


@flask_app.route("/api/apply_referral", methods=["POST"])
def apply_referral_api():
    data = request.get_json(silent=True) or {}
    try:
        referrer_id = int(data.get("referrer_id"))
        referred_id = int(data.get("referred_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid ids"}), 400
    if referrer_id == referred_id:
        return jsonify({"ok": False, "error": "self_referral"}), 400
    row = database.create_referral(referrer_id, referred_id)
    return jsonify({"ok": True, "referral": row})


@flask_app.route("/api/bot_info", methods=["GET"])
def bot_info_api():
    global BOT_USERNAME
    if not BOT_USERNAME:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10
            )
            data = resp.json()
            if data.get("ok"):
                BOT_USERNAME = data["result"].get("username") or ""
        except Exception:
            logger.exception("Failed to fetch bot username")
    return jsonify({"ok": True, "username": BOT_USERNAME})


@flask_app.route("/api/review", methods=["POST"])
def create_review_api():
    # Supports JSON or multipart (with optional image file)
    if request.content_type and "multipart/form-data" in request.content_type:
        order_id = request.form.get("order_id")
        rating = request.form.get("rating")
        comment = request.form.get("comment") or ""
        user_id = request.form.get("user_id")
        first_name = request.form.get("first_name")
        image_file = request.files.get("image")
    else:
        data = request.get_json(silent=True) or {}
        order_id = data.get("order_id")
        rating = data.get("rating")
        comment = data.get("comment") or ""
        user_id = data.get("user_id")
        first_name = data.get("first_name")
        image_file = None

    try:
        order_id = int(order_id)
        rating = int(rating)
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_params"}), 400

    order = database.get_order(order_id)
    if not order:
        return jsonify({"ok": False, "error": "order_not_found"}), 404
    if order.get("status") != "completed":
        return jsonify({"ok": False, "error": "order_not_completed"}), 400
    if order.get("customer_id") and int(order["customer_id"]) != user_id:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    image_url = None
    if image_file and image_file.filename:
        os.makedirs(REVIEWS_DIR, exist_ok=True)
        ext = os.path.splitext(image_file.filename)[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        filename = f"review_{order_id}_{user_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(REVIEWS_DIR, filename)
        image_file.save(filepath)
        image_url = f"{BASE_URL}/static/reviews/{filename}"

    try:
        result = database.create_review(
            order_id=order_id,
            user_id=user_id,
            rating=rating,
            comment=(comment or "").strip() or None,
            image_url=image_url,
            first_name=first_name,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "review": result["review"],
            "points_awarded": result["points_awarded"],
            "points": result["points"],
        }
    )


@flask_app.route("/api/user/points", methods=["GET"])
def user_points_api():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "error": "missing user_id"}), 400
    try:
        points = database.get_customer_points(int(user_id))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad user_id"}), 400
    return jsonify({"ok": True, "points": points})


@flask_app.route("/api/shop/<int:shop_id>/reviews/featured", methods=["GET"])
def featured_reviews_api(shop_id: int):
    reviews = database.get_featured_reviews(shop_id)
    for review in reviews:
        if isinstance(review, dict) and review.get("image_url"):
            review["image_url"] = absolutize_media_url(review.get("image_url"))
    return jsonify({"ok": True, "reviews": reviews})


@flask_app.route("/api/redeem_points", methods=["POST"])
def redeem_points_api():
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid user_id"}), 400

    result = database.redeem_points_for_coupon(user_id, cost=100, value=1.0)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(
        {
            "ok": True,
            "points": result["points"],
            "coupon_code": result["coupon"]["code"],
            "coupon": result["coupon"],
        }
    )


def resolve_bot_username() -> str:
    global BOT_USERNAME
    if BOT_USERNAME:
        return BOT_USERNAME
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10
        )
        data = resp.json()
        if data.get("ok"):
            BOT_USERNAME = data["result"].get("username") or ""
    except Exception:
        logger.exception("Failed to resolve bot username")
    return BOT_USERNAME


def notify_owner_tiktok_submission(submission: dict) -> None:
    lang = get_owner_lang()
    order_id = submission.get("order_id")
    order_no = format_order_number(order_id, lang) if order_id else "-"
    text = t(
        lang,
        "tiktok_owner_notify",
        id=submission["id"],
        user_id=submission["user_id"],
        order_no=order_no,
        url=submission["video_url"],
    )
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": t(lang, "btn_approve_tiktok"),
                    "callback_data": f"tiktok_approve_{submission['id']}",
                },
                {
                    "text": t(lang, "btn_reject_tiktok"),
                    "callback_data": f"tiktok_reject_{submission['id']}",
                },
            ]
        ]
    }
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_ID, "text": text, "reply_markup": keyboard},
            timeout=15,
        )
    except Exception:
        logger.exception("Failed to notify owner about TikTok submission")


@flask_app.route("/api/submit_tiktok", methods=["POST"])
def submit_tiktok_api():
    data = request.get_json(silent=True) or {}
    video_url = (data.get("video_url") or "").strip()
    user_id = data.get("user_id")
    order_id = data.get("order_id")
    if not video_url or not user_id:
        return jsonify({"ok": False, "error": "missing_params"}), 400
    if not (video_url.startswith("http://") or video_url.startswith("https://")):
        return jsonify({"ok": False, "error": "invalid_url"}), 400
    try:
        user_id = int(user_id)
        order_id = int(order_id) if order_id else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_ids"}), 400

    submission = database.create_tiktok_submission(user_id, video_url, order_id)
    notify_owner_tiktok_submission(submission)
    return jsonify({"ok": True, "submission_id": submission["id"]})


def order_manage_keyboard(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "btn_generate_payment"),
                    callback_data=f"genpay_{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "btn_confirm_payment"),
                    callback_data=f"confirmpay_{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "btn_cancel_order"),
                    callback_data=f"cancel_{order_id}",
                )
            ],
        ]
    )


async def notify_customer_text(bot, order: dict, key: str) -> None:
    customer_id = order.get("customer_id")
    if not customer_id:
        return
    cust_lang = detect_lang_code(order.get("customer_language") or "en")
    order_no = format_order_number(order["id"], cust_lang)
    try:
        await bot.send_message(
            chat_id=int(customer_id),
            text=t(cust_lang, key, order_no=order_no),
        )
    except Exception:
        logger.exception("Failed to notify customer %s for order %s", customer_id, order["id"])


async def manage_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    lang = get_lang(update, context)

    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return

    if query.data.startswith("manage_order_"):
        order_id = int(query.data.split("_")[-1])
        order = database.get_order(order_id)
        if not order:
            await query.edit_message_text(t(lang, "order_not_found"))
            return

        try:
            items = json.loads(order.get("items") or "[]")
        except json.JSONDecodeError:
            items = []

        lines = [
            t(lang, "order_manage_header", order_no=format_order_number(order_id, lang)),
            t(lang, "order_status", status=order.get("status") or "pending"),
            "",
            ot(lang, "items_label"),
        ]
        for item in items:
            lines.append(format_item_line(item, lang))
        lines.append("")
        lines.append(ot(lang, "total_label", total=float(order.get("total") or 0)))
        if order.get("payment_amount") is not None:
            lines.append(
                t(lang, "payment_amount_label", amount=float(order["payment_amount"]))
            )
        customer = order.get("customer_name") or ot(lang, "customer_unknown")
        lines.append(ot(lang, "customer_label", customer=customer))

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=order_manage_keyboard(lang, order_id),
        )
        return

    if query.data.startswith("confirmpay_"):
        order_id = int(query.data.split("_")[-1])
        order = database.get_order(order_id)
        if not order:
            await query.edit_message_text(t(lang, "order_not_found"))
            return
        order_no = format_order_number(order_id, lang)
        if order.get("status") != "awaiting_payment":
            await query.edit_message_text(
                t(
                    lang,
                    "order_not_awaiting_payment",
                    order_no=order_no,
                    status=order.get("status") or "pending",
                )
            )
            return
        database.update_order_status(order_id, "completed")
        await notify_customer_text(context.bot, order, "customer_order_paid")

        # Welcome coupon + referral rewards after payment confirmation
        customer_id = order.get("customer_id")
        if customer_id:
            await grant_post_payment_rewards(context.bot, int(customer_id))
            await send_review_invite(context.bot, order)

        await query.edit_message_text(t(lang, "order_marked_paid", order_no=order_no))
        return

    if query.data.startswith("cancel_"):
        order_id = int(query.data.split("_")[-1])
        order = database.get_order(order_id)
        if not order:
            await query.edit_message_text(t(lang, "order_not_found"))
            return
        database.update_order_status(order_id, "cancelled")
        await notify_customer_text(context.bot, order, "customer_order_cancelled")
        await query.edit_message_text(
            t(lang, "order_cancelled_msg", order_no=format_order_number(order_id, lang))
        )


async def genpay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    lang = get_lang(update, context)

    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    order_id = int(query.data.split("_")[-1])
    order = database.get_order(order_id)
    if not order:
        await query.edit_message_text(t(lang, "order_not_found"))
        return ConversationHandler.END

    shop = database.get_shop_settings(SHOP_ID)
    khqr_path = local_path_from_public_url((shop or {}).get("khqr_url"))
    if not shop or not shop.get("khqr_url") or not khqr_path:
        await query.message.reply_text(t(lang, "khqr_missing"))
        return ConversationHandler.END

    if not order.get("customer_id"):
        await query.message.reply_text(t(lang, "customer_id_missing"))
        return ConversationHandler.END

    context.user_data["pay_order_id"] = order_id
    await query.message.reply_text(t(lang, "prompt_payment_amount"))
    return WAITING_PAYMENT_AMOUNT


async def receive_payment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_PAYMENT_AMOUNT

    lang = get_lang(update, context)
    order_id = context.user_data.get("pay_order_id")
    if not order_id:
        await message.reply_text(t(lang, "cancelled"))
        return ConversationHandler.END

    try:
        amount = float(message.text.strip().replace("$", "").replace(",", ""))
        if amount <= 0:
            raise ValueError("non-positive")
    except ValueError:
        await message.reply_text(t(lang, "invalid_payment_amount"))
        return WAITING_PAYMENT_AMOUNT

    order = database.get_order(int(order_id))
    if not order:
        await message.reply_text(t(lang, "order_not_found"))
        context.user_data.pop("pay_order_id", None)
        return ConversationHandler.END

    shop = database.get_shop_settings(SHOP_ID)
    khqr_path = local_path_from_public_url((shop or {}).get("khqr_url"))
    if not shop or not khqr_path:
        await message.reply_text(t(lang, "khqr_missing"))
        context.user_data.pop("pay_order_id", None)
        return ConversationHandler.END

    cust_lang = detect_lang_code(order.get("customer_language") or "en")
    shop_name = shop_name_for_lang(shop, cust_lang)

    filename = f"order_{order_id}_payment.jpg"
    output_path = os.path.join(PAYMENTS_DIR, filename)
    try:
        generate_payment_image(
            khqr_path,
            output_path,
            amount=amount,
            shop_name=shop_name,
            customer_lang=cust_lang,
        )
        banner = t(cust_lang, "payment_transfer_text", amount=amount, shop_name=shop_name)
    except Exception:
        logger.exception("Failed to generate payment image for order %s", order_id)
        await message.reply_text(t(lang, "payment_send_failed"))
        context.user_data.pop("pay_order_id", None)
        return ConversationHandler.END

    payment_url = f"{BASE_URL}/static/payments/{filename}"
    customer_id = int(order["customer_id"])

    try:
        with open(output_path, "rb") as photo_file:
            await context.bot.send_photo(
                chat_id=customer_id,
                photo=photo_file,
                caption=banner,
            )
    except Exception:
        logger.exception("Failed to send payment photo to customer %s", customer_id)
        await message.reply_text(t(lang, "payment_send_failed"))
        context.user_data.pop("pay_order_id", None)
        return ConversationHandler.END

    database.update_order_payment(
        order_id=int(order_id),
        payment_amount=amount,
        payment_image_url=payment_url,
        status="awaiting_payment",
    )
    await message.reply_text(t(lang, "payment_page_sent"))
    context.user_data.pop("pay_order_id", None)
    return ConversationHandler.END


async def send_review_invite(bot, order: dict) -> None:
    customer_id = order.get("customer_id")
    if not customer_id:
        return
    cust_lang = detect_lang_code(order.get("customer_language") or "en")
    review_url = (
        f"{BASE_URL}/webapp/review.html?order_id={order['id']}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(cust_lang, "btn_leave_review"),
                    web_app=WebAppInfo(url=review_url),
                )
            ]
        ]
    )
    try:
        await bot.send_message(
            chat_id=int(customer_id),
            text=t(cust_lang, "review_invite"),
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to send review invite for order %s", order.get("id"))


async def grant_post_payment_rewards(bot, customer_id: int) -> None:
    """Give WELCOME5 once, and process referral $1 coupons on first completed order."""
    # Detect language from last order if possible
    lang = "en"
    try:
        # Prefer customer language from a recent order
        conn = database.get_connection()
        try:
            row = conn.execute(
                """
                SELECT customer_language FROM orders
                WHERE customer_id = ? ORDER BY id DESC LIMIT 1
                """,
                (customer_id,),
            ).fetchone()
            if row and row["customer_language"]:
                lang = detect_lang_code(row["customer_language"])
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to resolve customer language for rewards")

    welcome = database.grant_welcome_coupon(customer_id)
    if welcome:
        try:
            await bot.send_message(
                chat_id=customer_id,
                text=t(
                    lang,
                    "welcome_coupon_granted",
                    code=welcome["code"],
                    value=float(welcome["value"]),
                ),
            )
        except Exception:
            logger.exception("Failed to notify welcome coupon for %s", customer_id)

    completed = database.count_completed_orders(customer_id)
    if completed == 1:
        rewards = database.process_referral_rewards(customer_id)
        for item in rewards:
            uid = item["user_id"]
            coupon = item["coupon"]
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=t(
                        lang,
                        "referral_reward_granted",
                        code=coupon["code"],
                        value=float(coupon["value"]),
                    ),
                )
            except Exception:
                logger.exception("Failed to notify referral coupon for %s", uid)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    try:
        remember_owner_language(update)
        lang = get_lang(update, context)
        user = update.effective_user

        # Referral deep link: /start ref_{user_id}
        if context.args and user:
            arg = (context.args[0] or "").strip()
            if arg.startswith("ref_"):
                try:
                    referrer_id = int(arg.split("_", 1)[1])
                except (IndexError, ValueError):
                    referrer_id = None
                if referrer_id and referrer_id == user.id:
                    await message.reply_text(t(lang, "referral_self"))
                elif referrer_id:
                    try:
                        database.create_referral(referrer_id, user.id)
                        await message.reply_text(t(lang, "referral_saved"))
                    except Exception:
                        logger.exception("Failed to save referral")

        webapp_url = f"{BASE_URL}/webapp/index.html"
        welcome = t(lang, "welcome_message")
        try:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            t(lang, "btn_open_menu"),
                            web_app=WebAppInfo(url=webapp_url),
                        )
                    ]
                ]
            )
            await message.reply_text(welcome, reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to send WebApp button, sending fallback link")
            await message.reply_text(f"{welcome}\n{webapp_url}")

        logger.info("Replied to /start in chat %s", update.effective_chat.id)
    except Exception:
        logger.exception("start_command failed")
        try:
            await message.reply_text(
                "Welcome! Open the menu:\n"
                + f"{BASE_URL}/webapp/index.html"
            )
        except Exception:
            logger.exception("start_command fallback also failed")


async def reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return

    reviews = database.list_recent_reviews(15)
    if not reviews:
        await message.reply_text(t(lang, "reviews_empty"))
        return

    await message.reply_text(t(lang, "reviews_header"))
    for review in reviews:
        name = review.get("first_name") or review.get("customer_name") or "Guest"
        comment = (review.get("comment") or "").strip() or "-"
        featured = " ★" if int(review.get("is_featured") or 0) else ""
        text = t(
            lang,
            "review_line",
            id=review["id"],
            rating=review["rating"],
            name=f"{name}{featured}",
            comment=comment[:200],
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t(lang, "btn_feature_review"),
                        callback_data=f"feature_review_{review['id']}",
                    ),
                    InlineKeyboardButton(
                        t(lang, "btn_delete_review"),
                        callback_data=f"delete_review_{review['id']}",
                    ),
                ]
            ]
        )
        await message.reply_text(text, reply_markup=keyboard)


async def reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return

    if query.data.startswith("feature_review_"):
        review_id = int(query.data.split("_")[-1])
        if not database.set_review_featured(review_id, True):
            await query.edit_message_text(t(lang, "review_not_found"))
            return
        await query.edit_message_text(t(lang, "review_featured", id=review_id))
        return

    if query.data.startswith("delete_review_"):
        review_id = int(query.data.split("_")[-1])
        if not database.delete_review(review_id):
            await query.edit_message_text(t(lang, "review_not_found"))
            return
        await query.edit_message_text(t(lang, "review_deleted", id=review_id))


async def tiktok_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return

    submission_id = int(query.data.split("_")[-1])
    submission = database.get_tiktok_submission(submission_id)
    if not submission:
        await query.edit_message_text(t(lang, "tiktok_already_handled"))
        return
    if submission.get("status") != "pending" or int(submission.get("reward_given") or 0):
        await query.edit_message_text(t(lang, "tiktok_already_handled"))
        return

    user_id = int(submission["user_id"])
    order = (
        database.get_order(int(submission["order_id"]))
        if submission.get("order_id")
        else None
    )
    cust_lang = detect_lang_code((order or {}).get("customer_language") or "en")
    if query.data.startswith("tiktok_approve_"):
        code = f"TIKTOK5_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        coupon = database.create_and_assign_fixed_coupon(
            user_id=user_id,
            value=5.0,
            code=code,
            min_order=0,
        )
        database.update_tiktok_submission(submission_id, "approved", reward_given=1)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=t(cust_lang, "tiktok_reward_user", code=coupon["code"]),
            )
        except Exception:
            logger.exception("Failed to notify TikTok reward user %s", user_id)
        await query.edit_message_text(t(lang, "tiktok_approved", id=submission_id))
        return

    if query.data.startswith("tiktok_reject_"):
        database.update_tiktok_submission(submission_id, "rejected", reward_given=0)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=t(cust_lang, "tiktok_reject_user"),
            )
        except Exception:
            logger.exception("Failed to notify TikTok reject user %s", user_id)
        await query.edit_message_text(t(lang, "tiktok_rejected", id=submission_id))


def _draw_centered_text(draw, text, font, y, width, fill=(20, 20, 20)):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = max(20, (width - tw) // 2)
    draw.text((x, y), text, font=font, fill=fill)


def generate_table_qr_poster(shop: dict, bot_username: str) -> str:
    os.makedirs(POSTERS_DIR, exist_ok=True)
    link = f"https://t.me/{bot_username}?startapp=shop_{SHOP_ID}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    width, height = 1080, 1350
    canvas = Image.new("RGB", (width, height), (255, 248, 240))
    draw = ImageDraw.Draw(canvas)

    shop_name = shop.get("name_en") or "Shop"
    title_font = load_truetype(resolve_font_path("en", "latin"), 64) or ImageFont.load_default()
    sub_font = load_truetype(resolve_font_path("en", "latin"), 36) or ImageFont.load_default()
    _draw_centered_text(draw, shop_name, title_font, 60, width)
    _draw_centered_text(draw, "Scan to order", sub_font, 150, width, fill=(90, 90, 90))

    logo_path = local_path_from_public_url(shop.get("logo_url"))
    y_cursor = 220
    if logo_path and os.path.isfile(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((220, 220))
            lx = (width - logo.width) // 2
            canvas.paste(logo, (lx, y_cursor), logo)
            y_cursor += logo.height + 40
        except Exception:
            logger.exception("Failed to paste logo on table QR poster")

    qr_img = qr_img.resize((560, 560))
    qx = (width - qr_img.width) // 2
    canvas.paste(qr_img, (qx, y_cursor + 20))
    _draw_centered_text(draw, link, sub_font, y_cursor + 620, width, fill=(60, 60, 60))

    filename = f"table_qr_{uuid.uuid4().hex[:8]}.jpg"
    out_path = os.path.join(POSTERS_DIR, filename)
    canvas.save(out_path, format="JPEG", quality=92)
    return out_path


def generate_promotion_poster(
    shop: dict,
    promo_text: str,
    background_path: str | None = None,
) -> str:
    os.makedirs(POSTERS_DIR, exist_ok=True)
    width, height = 1080, 1350
    if background_path and os.path.isfile(background_path):
        canvas = Image.open(background_path).convert("RGB")
        canvas = canvas.resize((width, height))
    else:
        canvas = Image.new("RGB", (width, height), (255, 87, 34))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle((0, 0, width, 320), fill=(0, 0, 0, 140))
    odraw.rectangle((0, height - 420, width, height), fill=(0, 0, 0, 160))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    shop_name = shop.get("name_en") or "Shop"
    title_font = load_truetype(resolve_font_path("en", "latin"), 58) or ImageFont.load_default()
    promo_font = load_truetype(resolve_font_path("en", "latin"), 44) or ImageFont.load_default()
    _draw_centered_text(draw, shop_name, title_font, 80, width, fill=(255, 255, 255))

    # Wrap promo text simply
    words = (promo_text or "").split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=promo_font)
        if bbox[2] - bbox[0] > width - 80 and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    y = 180
    for line in lines[:4]:
        _draw_centered_text(draw, line, promo_font, y, width, fill=(255, 255, 255))
        y += 56

    khqr_path = local_path_from_public_url(shop.get("khqr_url"))
    if not khqr_path:
        raise FileNotFoundError("khqr_missing")
    khqr = Image.open(khqr_path).convert("RGB")
    khqr.thumbnail((360, 360))
    kx = (width - khqr.width) // 2
    canvas.paste(khqr, (kx, height - 400))
    small = load_truetype(resolve_font_path("en", "latin"), 32) or ImageFont.load_default()
    _draw_centered_text(draw, "Scan KHQR to pay", small, height - 50, width, fill=(255, 255, 255))

    filename = f"promo_{uuid.uuid4().hex[:8]}.jpg"
    out_path = os.path.join(POSTERS_DIR, filename)
    canvas.save(out_path, format="JPEG", quality=92)
    return out_path


async def poster_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "btn_poster_table_qr"),
                    callback_data="poster_type:table_qr",
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "btn_poster_promotion"),
                    callback_data="poster_type:promotion",
                )
            ],
        ]
    )
    await message.reply_text(t(lang, "poster_choose_type"), reply_markup=keyboard)
    return WAITING_POSTER_TYPE


async def poster_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    poster_type = query.data.split(":", 1)[1]
    if poster_type == "table_qr":
        shop = database.get_shop_settings(SHOP_ID) or {}
        username = resolve_bot_username()
        if not username:
            await query.edit_message_text(t(lang, "poster_need_bot_username"))
            return ConversationHandler.END
        try:
            path = generate_table_qr_poster(shop, username)
            with open(path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo,
                    caption=t(lang, "poster_ready"),
                )
            await query.edit_message_text(t(lang, "poster_ready"))
        except Exception:
            logger.exception("table_qr poster failed")
            await query.edit_message_text(t(lang, "poster_failed"))
        return ConversationHandler.END

    context.user_data["poster"] = {"type": "promotion"}
    await query.edit_message_text(t(lang, "poster_prompt_promo_text"))
    return WAITING_PROMO_TEXT


async def receive_promo_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_PROMO_TEXT
    lang = get_lang(update, context)
    context.user_data.setdefault("poster", {})["promo_text"] = message.text.strip()
    await message.reply_text(t(lang, "poster_prompt_bg"))
    return WAITING_PROMO_BG


async def receive_promo_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not is_owner(update):
        return WAITING_PROMO_BG
    lang = get_lang(update, context)
    if not message.photo:
        await message.reply_text(t(lang, "poster_prompt_bg"))
        return WAITING_PROMO_BG

    os.makedirs(POSTERS_DIR, exist_ok=True)
    bg_path = os.path.join(POSTERS_DIR, f"bg_{uuid.uuid4().hex[:8]}.jpg")
    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(bg_path)
    return await finish_promotion_poster(update, context, bg_path)


async def skip_promo_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update):
        return ConversationHandler.END
    return await finish_promotion_poster(update, context, None)


async def finish_promotion_poster(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    background_path: str | None,
) -> int:
    message = update.effective_message
    lang = get_lang(update, context)
    promo_text = (context.user_data.get("poster") or {}).get("promo_text") or ""
    shop = database.get_shop_settings(SHOP_ID) or {}
    try:
        path = generate_promotion_poster(shop, promo_text, background_path)
        if message:
            with open(path, "rb") as photo:
                await message.reply_photo(photo=photo, caption=t(lang, "poster_ready"))
    except FileNotFoundError:
        if message:
            await message.reply_text(t(lang, "poster_khqr_missing"))
    except Exception:
        logger.exception("promotion poster failed")
        if message:
            await message.reply_text(t(lang, "poster_failed"))
    context.user_data.pop("poster", None)
    return ConversationHandler.END


async def mycoupons_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    lang = get_lang(update, context)
    coupons = database.get_user_unused_coupons(user.id)
    if not coupons:
        await message.reply_text(t(lang, "mycoupons_empty"))
        return

    lines = [t(lang, "mycoupons_header"), ""]
    for coupon in coupons:
        expires = ""
        if coupon.get("expires_at"):
            expires = t(lang, "mycoupons_expires", date=str(coupon["expires_at"])[:10])
        key = "mycoupons_line_percent" if coupon["type"] == "percent" else "mycoupons_line_fixed"
        lines.append(
            t(
                lang,
                key,
                code=coupon["code"],
                value=float(coupon["value"]),
                min_order=float(coupon.get("min_order") or 0),
                expires=expires,
            )
        )
    await message.reply_text("\n".join(lines))


async def createcoupon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return ConversationHandler.END

    context.user_data["new_coupon"] = {}
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "btn_coupon_fixed"), callback_data="coupon_type:fixed"
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "btn_coupon_percent"), callback_data="coupon_type:percent"
                )
            ],
        ]
    )
    await message.reply_text(t(lang, "coupon_create_prompt_type"), reply_markup=keyboard)
    return WAITING_COUPON_TYPE


async def coupon_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    coupon_type = query.data.split(":", 1)[1]
    context.user_data.setdefault("new_coupon", {})["type"] = coupon_type
    prompt = (
        "coupon_prompt_value_percent"
        if coupon_type == "percent"
        else "coupon_prompt_value_fixed"
    )
    await query.edit_message_text(t(lang, prompt))
    return WAITING_COUPON_VALUE


async def receive_coupon_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_COUPON_VALUE
    lang = get_lang(update, context)
    try:
        value = float(message.text.strip())
        if value <= 0:
            raise ValueError("non-positive")
        coupon_type = (context.user_data.get("new_coupon") or {}).get("type")
        if coupon_type == "percent" and value > 100:
            raise ValueError("percent too high")
    except ValueError:
        await message.reply_text(t(lang, "coupon_invalid_number"))
        return WAITING_COUPON_VALUE
    context.user_data.setdefault("new_coupon", {})["value"] = value
    await message.reply_text(t(lang, "coupon_prompt_min_order"))
    return WAITING_COUPON_MIN_ORDER


async def receive_coupon_min_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_COUPON_MIN_ORDER
    lang = get_lang(update, context)
    try:
        min_order = float(message.text.strip())
        if min_order < 0:
            raise ValueError("negative")
    except ValueError:
        await message.reply_text(t(lang, "coupon_invalid_number"))
        return WAITING_COUPON_MIN_ORDER
    context.user_data.setdefault("new_coupon", {})["min_order"] = min_order
    await message.reply_text(t(lang, "coupon_prompt_usage_limit"))
    return WAITING_COUPON_USAGE_LIMIT


async def receive_coupon_usage_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_COUPON_USAGE_LIMIT
    lang = get_lang(update, context)
    try:
        usage_limit = int(float(message.text.strip()))
        if usage_limit < 1:
            raise ValueError("too small")
    except ValueError:
        await message.reply_text(t(lang, "coupon_invalid_number"))
        return WAITING_COUPON_USAGE_LIMIT
    context.user_data.setdefault("new_coupon", {})["usage_limit"] = usage_limit
    await message.reply_text(t(lang, "coupon_prompt_expiry"))
    return WAITING_COUPON_EXPIRY


async def receive_coupon_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_COUPON_EXPIRY
    lang = get_lang(update, context)
    try:
        days = int(float(message.text.strip()))
        if days < 0:
            raise ValueError("negative")
    except ValueError:
        await message.reply_text(t(lang, "coupon_invalid_number"))
        return WAITING_COUPON_EXPIRY

    data = context.user_data.get("new_coupon") or {}
    expires_at = None
    expires_label = t(lang, "coupon_no_expiry")
    if days > 0:
        expires_at = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
        expires_label = expires_at

    code = database.generate_coupon_code("CPN", 6)
    coupon = database.create_coupon(
        code=code,
        coupon_type=data["type"],
        value=float(data["value"]),
        min_order=float(data.get("min_order") or 0),
        shop_id=SHOP_ID,
        usage_limit=int(data.get("usage_limit") or 1),
        expires_at=expires_at,
    )
    value_label = (
        f"{float(coupon['value']):.0f}%"
        if coupon["type"] == "percent"
        else f"${float(coupon['value']):.2f}"
    )
    await message.reply_text(
        t(
            lang,
            "coupon_created",
            code=coupon["code"],
            type=coupon["type"],
            value=value_label,
            min_order=float(coupon.get("min_order") or 0),
            usage_limit=int(coupon.get("usage_limit") or 1),
            expires=expires_label,
        )
    )
    context.user_data.pop("new_coupon", None)
    return ConversationHandler.END


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END

    try:
        remember_owner_language(update)
        lang = get_lang(update, context)

        if not is_owner(update):
            await message.reply_text(t(lang, "owner_only"))
            return ConversationHandler.END

        shop = database.get_shop_settings(SHOP_ID)
        if not shop:
            await message.reply_text(t(lang, "shop_not_found"))
            return ConversationHandler.END

        await message.reply_text(
            format_settings_message(shop, lang),
            reply_markup=settings_keyboard(lang),
        )
        logger.info("Replied to /settings in chat %s", update.effective_chat.id)
    except Exception:
        logger.exception("settings_command failed")
        try:
            await message.reply_text(
                "Settings error. Try /settings again, or restart the bot."
            )
        except Exception:
            logger.exception("settings_command fallback also failed")
    return ConversationHandler.END


async def preview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    lang = get_lang(update, context)

    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return

    bot_username = context.bot.username
    if not bot_username:
        bot_me = await context.bot.get_me()
        bot_username = bot_me.username

    preview_link = f"https://t.me/{bot_username}?startapp=shop_{SHOP_ID}"
    webapp_url = f"{BASE_URL}/webapp/index.html"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "btn_preview"), web_app=WebAppInfo(url=webapp_url))],
            [InlineKeyboardButton(t(lang, "btn_deep_link"), url=preview_link)],
        ]
    )
    await message.reply_text(
        t(lang, "preview_message", link=preview_link),
        reply_markup=keyboard,
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()
    lang = get_lang(update, context)

    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    if query.data == "set_shop_name":
        await query.message.reply_text(t(lang, "prompt_shop_name"))
        return WAITING_SHOP_NAME

    if query.data == "upload_logo":
        await query.message.reply_text(t(lang, "prompt_logo"))
        return WAITING_LOGO

    if query.data == "upload_khqr":
        await query.message.reply_text(t(lang, "prompt_khqr"))
        return WAITING_KHQR

    if query.data == "set_group_invite":
        await query.message.reply_text(t(lang, "prompt_group_invite"))
        return WAITING_GROUP_INVITE

    if query.data == "set_background_image":
        await query.message.reply_text(t(lang, "prompt_background_image"))
        return WAITING_BACKGROUND_IMAGE

    if query.data == "add_menu_item":
        context.user_data["new_item"] = {}
        await query.message.reply_text(t(lang, "prompt_item_category"))
        return WAITING_ITEM_CATEGORY

    if query.data == "set_primary_color":
        await query.message.reply_text(
            t(lang, "choose_primary_color"),
            reply_markup=color_picker_keyboard(lang, "primary_color"),
        )
        return WAITING_PRIMARY_COLOR

    if query.data == "set_background_color":
        await query.message.reply_text(
            t(lang, "choose_background_color"),
            reply_markup=color_picker_keyboard(lang, "background_color"),
        )
        return WAITING_BACKGROUND_COLOR

    return ConversationHandler.END


async def receive_group_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_GROUP_INVITE
    lang = get_lang(update, context)
    link = message.text.strip()
    if not (
        link.startswith("https://t.me/")
        or link.startswith("http://t.me/")
        or link.startswith("https://telegram.me/")
    ):
        await message.reply_text(t(lang, "invalid_group_invite"))
        return WAITING_GROUP_INVITE

    database.update_shop_settings(SHOP_ID, group_invite_link=link)
    shop = database.get_shop_settings(SHOP_ID)
    await message.reply_text(
        f"{t(lang, 'group_invite_saved')}\n\n{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    return ConversationHandler.END


async def color_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    lang = get_lang(update, context)

    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    parts = query.data.split(":")
    if len(parts) != 3:
        return ConversationHandler.END

    _, field, hex_value = parts
    if field not in ("primary_color", "background_color"):
        return ConversationHandler.END
    if not HEX_COLOR_PATTERN.match(hex_value):
        return ConversationHandler.END

    value = hex_value.upper()
    database.update_shop_settings(SHOP_ID, **{field: value})
    shop = database.get_shop_settings(SHOP_ID)
    confirm_key = "primary_updated" if field == "primary_color" else "background_updated"
    await query.edit_message_text(
        f"{t(lang, confirm_key, value=value)}\n\n{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    context.user_data.pop("color_field", None)
    return ConversationHandler.END


async def custom_color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    lang = get_lang(update, context)

    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return ConversationHandler.END

    parts = query.data.split(":")
    if len(parts) != 2:
        return ConversationHandler.END

    _, field = parts
    if field not in ("primary_color", "background_color"):
        return ConversationHandler.END

    context.user_data["color_field"] = field
    await query.message.reply_text(t(lang, "prompt_custom_color"))
    return WAITING_CUSTOM_COLOR


async def receive_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_SHOP_NAME

    lang = get_lang(update, context)
    parts = [part.strip() for part in message.text.split("|")]
    if len(parts) != 3 or not all(parts):
        await message.reply_text(t(lang, "invalid_shop_name"))
        return WAITING_SHOP_NAME

    name_en, name_km, name_zh = parts
    database.update_shop_settings(
        SHOP_ID,
        name_en=name_en,
        name_km=name_km,
        name_zh=name_zh,
    )
    shop = database.get_shop_settings(SHOP_ID)
    await message.reply_text(
        f"{t(lang, 'shop_names_updated')}\n\n{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    return ConversationHandler.END


async def receive_custom_color(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_CUSTOM_COLOR

    lang = get_lang(update, context)
    field = context.user_data.get("color_field")
    if field not in ("primary_color", "background_color"):
        await message.reply_text(t(lang, "cancelled"))
        return ConversationHandler.END

    value = message.text.strip()
    if not HEX_COLOR_PATTERN.match(value):
        await message.reply_text(t(lang, "invalid_color"))
        return WAITING_CUSTOM_COLOR

    return await save_color_and_confirm(update, context, field, value)


async def receive_logo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not is_owner(update):
        return WAITING_LOGO

    lang = get_lang(update, context)

    if not message.photo:
        await message.reply_text(t(lang, "logo_need_photo"))
        return WAITING_LOGO

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(LOGO_PATH)

    logo_url = f"{BASE_URL}/static/logo.png"
    database.update_shop_settings(SHOP_ID, logo_url=logo_url)
    shop = database.get_shop_settings(SHOP_ID)
    await message.reply_text(
        f"{t(lang, 'logo_uploaded', url=logo_url)}\n\n{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    return ConversationHandler.END


async def receive_khqr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not is_owner(update):
        return WAITING_KHQR

    lang = get_lang(update, context)

    if not message.photo:
        await message.reply_text(t(lang, "khqr_need_photo"))
        return WAITING_KHQR

    os.makedirs(KHQR_DIR, exist_ok=True)
    filename = f"shop_{SHOP_ID}_khqr.jpg"
    filepath = os.path.join(KHQR_DIR, filename)

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(filepath)

    khqr_url = f"{BASE_URL}/static/khqr/{filename}"
    database.update_shop_settings(SHOP_ID, khqr_url=khqr_url)
    shop = database.get_shop_settings(SHOP_ID)
    await message.reply_text(
        f"{t(lang, 'khqr_uploaded', url=khqr_url)}\n\n{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    return ConversationHandler.END


async def receive_background_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not is_owner(update):
        return WAITING_BACKGROUND_IMAGE

    lang = get_lang(update, context)

    if not message.photo:
        await message.reply_text(t(lang, "background_image_need_photo"))
        return WAITING_BACKGROUND_IMAGE

    os.makedirs(BG_DIR, exist_ok=True)
    filename = f"shop_{SHOP_ID}_bg.jpg"
    filepath = os.path.join(BG_DIR, filename)

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(filepath)

    bg_url = f"{BASE_URL}/static/backgrounds/{filename}"
    database.update_shop_settings(SHOP_ID, background_image_url=bg_url)
    shop = database.get_shop_settings(SHOP_ID)
    await message.reply_text(
        f"{t(lang, 'background_image_uploaded', url=bg_url)}\n\n"
        f"{format_settings_message(shop, lang)}",
        reply_markup=settings_keyboard(lang),
    )
    return ConversationHandler.END


async def additem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END

    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return ConversationHandler.END

    context.user_data["new_item"] = {}
    await message.reply_text(t(lang, "prompt_item_category"))
    return WAITING_ITEM_CATEGORY


async def receive_item_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_ITEM_CATEGORY

    lang = get_lang(update, context)
    category = message.text.strip()
    if not category:
        await message.reply_text(t(lang, "prompt_item_category"))
        return WAITING_ITEM_CATEGORY

    context.user_data.setdefault("new_item", {})["category"] = category
    await message.reply_text(t(lang, "prompt_item_name"))
    return WAITING_ITEM_NAME


async def receive_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_ITEM_NAME

    lang = get_lang(update, context)
    parts = [part.strip() for part in message.text.split("|")]
    if len(parts) != 3 or not all(parts):
        await message.reply_text(t(lang, "invalid_item_name"))
        return WAITING_ITEM_NAME

    name_en, name_km, name_zh = parts
    item = context.user_data.setdefault("new_item", {})
    item["name_en"] = name_en
    item["name_km"] = name_km
    item["name_zh"] = name_zh
    await message.reply_text(t(lang, "prompt_item_price"))
    return WAITING_ITEM_PRICE


async def receive_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_ITEM_PRICE

    lang = get_lang(update, context)
    try:
        price = float(message.text.strip())
        if price < 0:
            raise ValueError("negative")
    except ValueError:
        await message.reply_text(t(lang, "invalid_item_price"))
        return WAITING_ITEM_PRICE

    context.user_data.setdefault("new_item", {})["price"] = price
    await message.reply_text(t(lang, "prompt_item_vegetarian"))
    return WAITING_ITEM_VEGETARIAN


async def receive_item_vegetarian(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_ITEM_VEGETARIAN

    lang = get_lang(update, context)
    answer = message.text.strip().lower()
    yes_values = {"yes", "y", "true", "1", "是", "素", "vegetarian"}
    no_values = {"no", "n", "false", "0", "否", "不是"}
    if answer in yes_values:
        is_veg = 1
    elif answer in no_values:
        is_veg = 0
    else:
        await message.reply_text(t(lang, "invalid_item_vegetarian"))
        return WAITING_ITEM_VEGETARIAN

    context.user_data.setdefault("new_item", {})["is_vegetarian"] = is_veg
    await message.reply_text(t(lang, "prompt_item_photo"))
    return WAITING_ITEM_PHOTO


def festival_name_for_lang(festival: dict, lang: str) -> str:
    key = f"name_{lang}" if lang in ("en", "km", "zh") else "name_en"
    return festival.get(key) or festival.get("name_en") or "Festival"


async def festival_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return

    festivals = database.list_festivals()
    if not festivals:
        await message.reply_text(t(lang, "festival_none"))
        return

    active = database.get_active_festival(SHOP_ID)
    lines = [t(lang, "festival_list_header")]
    if active:
        lines.append(
            t(lang, "festival_active_label", name=festival_name_for_lang(active, lang))
        )
    else:
        lines.append(t(lang, "festival_not_active"))

    buttons = []
    for fest in festivals:
        veg = t(lang, "festival_veg_tag") if int(fest.get("is_vegetarian") or 0) else ""
        lines.append(
            t(
                lang,
                "festival_line",
                name=festival_name_for_lang(fest, lang),
                start=fest.get("start_date") or "-",
                end=fest.get("end_date") or "-",
                discount=float(fest.get("discount_percent") or 0),
                veg=veg,
            )
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{t(lang, 'btn_activate_festival')}: {festival_name_for_lang(fest, lang)}",
                    callback_data=f"festival_activate_{fest['id']}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                t(lang, "btn_clear_festival"),
                callback_data="festival_clear",
            )
        ]
    )
    await message.reply_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def festival_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return

    if query.data == "festival_clear":
        database.set_active_festival(SHOP_ID, None)
        await query.edit_message_text(t(lang, "festival_cleared"))
        return

    if query.data.startswith("festival_activate_"):
        festival_id = int(query.data.split("_")[-1])
        fest = database.get_festival(festival_id)
        if not fest:
            await query.edit_message_text(t(lang, "festival_none"))
            return
        database.set_active_festival(SHOP_ID, festival_id)
        await query.edit_message_text(
            t(
                lang,
                "festival_activated",
                name=festival_name_for_lang(fest, lang),
                discount=float(fest.get("discount_percent") or 0),
            )
        )


async def notify_queue_user(bot, entry: dict, key: str) -> bool:
    user_id = entry.get("user_id")
    if not user_id:
        return False
    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=t(
                "en",
                key,
                number=entry.get("queue_number"),
            ),
        )
        return True
    except Exception:
        logger.exception("Failed to notify queue user %s", user_id)
        return False


def queue_keyboard(lang: str, entries: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                t(lang, "btn_queue_next"),
                callback_data="queue_next",
            )
        ]
    ]
    for entry in entries:
        if entry.get("status") in ("waiting", "ordering"):
            rows.append(
                [
                    InlineKeyboardButton(
                        t(lang, "btn_queue_call", number=entry["queue_number"]),
                        callback_data=f"queue_call_{entry['id']}",
                    )
                ]
            )
    return InlineKeyboardMarkup(rows)


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return

    entries = database.list_active_queue(SHOP_ID)
    if not entries:
        await message.reply_text(t(lang, "queue_empty"))
        return

    lines = [t(lang, "queue_header")]
    for entry in entries:
        lines.append(
            t(
                lang,
                "queue_line",
                number=entry["queue_number"],
                size=entry["party_size"],
                status=entry["status"],
                user_id=entry["user_id"],
            )
        )
    await message.reply_text(
        "\n".join(lines),
        reply_markup=queue_keyboard(lang, entries),
    )


async def queue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    lang = get_lang(update, context)
    if not is_owner(update):
        await query.edit_message_text(t(lang, "owner_only"))
        return

    if query.data == "queue_next":
        entry = database.advance_next_waiting(SHOP_ID)
        if not entry:
            await query.edit_message_text(t(lang, "queue_no_waiting"))
            return
        ok = await notify_queue_user(context.bot, entry, "queue_notify_ordering")
        notified = t(lang, "queue_notify_ok" if ok else "queue_notify_failed")
        await query.edit_message_text(
            t(
                lang,
                "queue_advanced",
                number=entry["queue_number"],
                notified=notified,
            )
        )
        return

    if query.data.startswith("queue_call_"):
        queue_id = int(query.data.split("_")[-1])
        entry = database.get_queue_entry(queue_id)
        if not entry:
            await query.edit_message_text(t(lang, "queue_empty"))
            return
        entry = database.update_queue_status(queue_id, "ready")
        ok = await notify_queue_user(context.bot, entry, "queue_notify_ready")
        notified = t(lang, "queue_notify_ok" if ok else "queue_notify_failed")
        await query.edit_message_text(
            t(
                lang,
                "queue_called",
                number=entry["queue_number"],
                notified=notified,
            )
        )


def format_stats_message(lang: str, stats: dict) -> str:
    period_label = "today" if stats.get("period") == "today" else "week"
    lines = [
        t(lang, "stats_header", period=period_label),
        t(lang, "stats_orders", count=stats.get("total_orders", 0)),
        t(lang, "stats_revenue", revenue=float(stats.get("revenue") or 0)),
        "",
        t(lang, "stats_top_items"),
    ]
    top = stats.get("top_items") or []
    if not top:
        lines.append(t(lang, "stats_no_items"))
    else:
        for item in top:
            lines.append(
                t(lang, "stats_item_line", name=item["name"], qty=item["qty"])
            )
    return "\n".join(lines)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return
    stats = database.get_order_stats(SHOP_ID, "today")
    await message.reply_text(format_stats_message(lang, stats))


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return
    stats = database.get_order_stats(SHOP_ID, "week")
    await message.reply_text(format_stats_message(lang, stats))


def parse_iso_date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


async def send_orders_csv(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_date: str,
    end_date: str,
) -> None:
    message = update.effective_message
    lang = get_lang(update, context)
    orders = database.get_orders_in_range(SHOP_ID, start_date, end_date)
    if not orders:
        if message:
            await message.reply_text(t(lang, "export_empty"))
        return

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "customer_id",
            "customer_name",
            "status",
            "order_type",
            "queue_id",
            "total",
            "discount_amount",
            "coupon_code",
            "items",
        ]
    )
    for order in orders:
        writer.writerow(
            [
                order.get("id"),
                order.get("created_at"),
                order.get("customer_id"),
                order.get("customer_name"),
                order.get("status"),
                order.get("order_type"),
                order.get("queue_id"),
                order.get("total"),
                order.get("discount_amount"),
                order.get("coupon_code"),
                order.get("items"),
            ]
        )
    data = buf.getvalue().encode("utf-8-sig")
    filename = f"orders_{start_date}_{end_date}.csv"
    if message:
        await message.reply_document(
            document=InputFile(BytesIO(data), filename=filename),
            caption=t(lang, "export_ready", start=start_date, end=end_date),
        )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END
    lang = get_lang(update, context)
    if not is_owner(update):
        await message.reply_text(t(lang, "owner_only"))
        return ConversationHandler.END

    args = context.args or []
    if len(args) >= 2:
        start = parse_iso_date(args[0])
        end = parse_iso_date(args[1])
        if not start or not end:
            await message.reply_text(t(lang, "export_usage"))
            return ConversationHandler.END
        if start > end:
            start, end = end, start
        await send_orders_csv(update, context, start, end)
        return ConversationHandler.END

    await message.reply_text(t(lang, "export_prompt_start"))
    return WAITING_EXPORT_START


async def receive_export_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_EXPORT_START
    lang = get_lang(update, context)
    start = parse_iso_date(message.text)
    if not start:
        await message.reply_text(t(lang, "export_invalid_date"))
        return WAITING_EXPORT_START
    context.user_data["export_start"] = start
    await message.reply_text(t(lang, "export_prompt_end"))
    return WAITING_EXPORT_END


async def receive_export_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not message.text or not is_owner(update):
        return WAITING_EXPORT_END
    lang = get_lang(update, context)
    end = parse_iso_date(message.text)
    if not end:
        await message.reply_text(t(lang, "export_invalid_date"))
        return WAITING_EXPORT_END
    start = context.user_data.get("export_start")
    if not start:
        await message.reply_text(t(lang, "export_prompt_start"))
        return WAITING_EXPORT_START
    if start > end:
        start, end = end, start
    await send_orders_csv(update, context, start, end)
    context.user_data.pop("export_start", None)
    return ConversationHandler.END


async def finish_add_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str | None,
) -> int:
    lang = get_lang(update, context)
    item_data = context.user_data.get("new_item") or {}
    message = update.effective_message

    required = ("category", "name_en", "name_km", "name_zh", "price")
    if not all(key in item_data for key in required):
        if message:
            await message.reply_text(t(lang, "cancelled"))
        context.user_data.pop("new_item", None)
        return ConversationHandler.END

    saved = database.add_menu_item(
        SHOP_ID,
        category=item_data["category"],
        name_en=item_data["name_en"],
        name_km=item_data["name_km"],
        name_zh=item_data["name_zh"],
        price=float(item_data["price"]),
        image_url=image_url,
        is_vegetarian=int(item_data.get("is_vegetarian") or 0),
    )

    name_key = f"name_{lang}" if lang in ("en", "km", "zh") else "name_en"
    display_name = saved.get(name_key) or saved.get("name_en")
    category_label = localize_category(saved.get("category") or "")[lang]
    image_label = saved.get("image_url") or t(lang, "no_image")

    if message:
        await message.reply_text(
            t(
                lang,
                "item_added",
                category=category_label,
                name=display_name,
                price=float(saved.get("price") or 0),
                image=image_label,
            ),
            reply_markup=settings_keyboard(lang),
        )

    context.user_data.pop("new_item", None)
    return ConversationHandler.END


async def receive_item_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message or not is_owner(update):
        return WAITING_ITEM_PHOTO

    lang = get_lang(update, context)
    if not message.photo:
        await message.reply_text(t(lang, "prompt_item_photo"))
        return WAITING_ITEM_PHOTO

    os.makedirs(MENU_DIR, exist_ok=True)
    filename = f"item_{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(MENU_DIR, filename)

    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(filepath)

    image_url = f"{BASE_URL}/static/menu/{filename}"
    return await finish_add_item(update, context, image_url)


async def skip_item_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update):
        return ConversationHandler.END
    return await finish_add_item(update, context, None)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if message:
        lang = get_lang(update, context)
        context.user_data.pop("color_field", None)
        context.user_data.pop("new_item", None)
        context.user_data.pop("pay_order_id", None)
        context.user_data.pop("new_coupon", None)
        context.user_data.pop("poster", None)
        context.user_data.pop("export_start", None)
        await message.reply_text(t(lang, "cancelled"))
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update %s caused error: %s", update, context.error)


def build_settings_conversation() -> ConversationHandler:
    color_handlers = [
        CallbackQueryHandler(
            color_pick_callback,
            pattern=r"^pick_color:(primary_color|background_color):#[0-9A-Fa-f]{6}$",
        ),
        CallbackQueryHandler(
            custom_color_callback,
            pattern=r"^custom_color:(primary_color|background_color)$",
        ),
    ]
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                settings_callback,
                pattern=(
                    r"^(set_shop_name|set_primary_color|set_background_color|"
                    r"set_background_image|upload_logo|upload_khqr|set_group_invite|"
                    r"add_menu_item)$"
                ),
            ),
            CommandHandler("additem", additem_command),
        ],
        states={
            WAITING_SHOP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_shop_name),
            ],
            WAITING_PRIMARY_COLOR: color_handlers,
            WAITING_BACKGROUND_COLOR: color_handlers,
            WAITING_CUSTOM_COLOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_color),
            ],
            WAITING_LOGO: [
                MessageHandler(filters.PHOTO, receive_logo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_logo),
            ],
            WAITING_KHQR: [
                MessageHandler(filters.PHOTO, receive_khqr),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_khqr),
            ],
            WAITING_GROUP_INVITE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_invite),
            ],
            WAITING_BACKGROUND_IMAGE: [
                MessageHandler(filters.PHOTO, receive_background_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_background_image),
            ],
            WAITING_ITEM_CATEGORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_category),
            ],
            WAITING_ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_name),
            ],
            WAITING_ITEM_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_price),
            ],
            WAITING_ITEM_VEGETARIAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_vegetarian),
            ],
            WAITING_ITEM_PHOTO: [
                MessageHandler(filters.PHOTO, receive_item_photo),
                CommandHandler("skip", skip_item_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )


def build_payment_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(genpay_callback, pattern=r"^genpay_\d+$"),
        ],
        states={
            WAITING_PAYMENT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_amount),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )


def build_coupon_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("createcoupon", createcoupon_command)],
        states={
            WAITING_COUPON_TYPE: [
                CallbackQueryHandler(
                    coupon_type_callback, pattern=r"^coupon_type:(fixed|percent)$"
                ),
            ],
            WAITING_COUPON_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coupon_value),
            ],
            WAITING_COUPON_MIN_ORDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coupon_min_order),
            ],
            WAITING_COUPON_USAGE_LIMIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coupon_usage_limit),
            ],
            WAITING_COUPON_EXPIRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coupon_expiry),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )


def build_poster_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("poster", poster_command)],
        states={
            WAITING_POSTER_TYPE: [
                CallbackQueryHandler(
                    poster_type_callback, pattern=r"^poster_type:(table_qr|promotion)$"
                ),
            ],
            WAITING_PROMO_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_promo_text),
            ],
            WAITING_PROMO_BG: [
                MessageHandler(filters.PHOTO, receive_promo_bg),
                CommandHandler("skip", skip_promo_bg),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )


def build_export_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("export", export_command)],
        states={
            WAITING_EXPORT_START: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_export_start),
            ],
            WAITING_EXPORT_END: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_export_end),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )


def run_flask():
    logger.info("Flask server starting on http://0.0.0.0:%s", FLASK_PORT)
    flask_app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False, threaded=True)


async def remember_owner_language_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    remember_owner_language(update)


def _build_application() -> Application:
    # Longer timeouts help on slow / flaky networks to api.telegram.org
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("preview", preview_command))
    application.add_handler(CommandHandler("mycoupons", mycoupons_command))
    application.add_handler(CommandHandler("reviews", reviews_command))
    application.add_handler(CommandHandler("festival", festival_command))
    application.add_handler(CommandHandler("queue", queue_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(build_settings_conversation())
    application.add_handler(build_payment_conversation())
    application.add_handler(build_coupon_conversation())
    application.add_handler(build_poster_conversation())
    application.add_handler(build_export_conversation())
    application.add_handler(
        CallbackQueryHandler(
            manage_order_callback,
            pattern=r"^(manage_order_|confirmpay_|cancel_)\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            reviews_callback,
            pattern=r"^(feature_review_|delete_review_)\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            tiktok_callback,
            pattern=r"^(tiktok_approve_|tiktok_reject_)\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            festival_callback,
            pattern=r"^(festival_activate_\d+|festival_clear)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            queue_callback,
            pattern=r"^(queue_next|queue_call_\d+)$",
        )
    )
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.User(OWNER_ID),
            remember_owner_language_handler,
        ),
        group=1,
    )
    application.add_error_handler(error_handler)
    return application


def run_bot():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Retry forever so a Telegram timeout does not leave Flask up with a dead bot
    while True:
        try:
            application = _build_application()
            logger.info(
                "Starting BongPrak bot polling... (owner_lang=%s)", get_owner_lang()
            )
            application.run_polling(
                drop_pending_updates=True,
                stop_signals=None,
                bootstrap_retries=10,
            )
            break
        except Exception:
            logger.exception("Bot polling crashed; retrying in 5 seconds...")
            time.sleep(5)


def main():
    ensure_single_instance()
    logger.info("Using BASE_URL=%s OWNER_ID=%s", BASE_URL, OWNER_ID)
    configure_telegram_webapp()

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    run_flask()


if __name__ == "__main__":
    main()
