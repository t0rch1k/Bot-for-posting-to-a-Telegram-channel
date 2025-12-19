import asyncio
import json
import os
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID

class PostStates(StatesGroup):
    title = State()
    body = State()
    ask_tags = State()
    tags = State()
    ask_button = State()
    button_text = State()
    button_url = State()
    add_more_buttons = State()
    ask_media = State()
    media = State()
    confirm = State()
    schedule_time = State()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())
SCHEDULE_FILE = "scheduled_posts.json"
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='📝 Создать пост', callback_data='create_post')]])
    await message.answer("Привет! Я бот для постинга в канал.", reply_markup=kb)

@dp.message(F.text == "/scheduled")
async def view_scheduled_posts(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not os.path.exists(SCHEDULE_FILE):
        await message.answer("❌ Файл не найден.")
        return
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        posts = f.readlines()
    if not posts:
        await message.answer("⛔️ Нет отложенных постов.")
        return
    await state.update_data(scheduled_posts=posts, current_index=0)
    await send_post_preview(message.chat.id, posts, 0)

async def send_post_preview(chat_id, posts, index):
    try:
        data = json.loads(posts[index])
        title = data.get("title", "Без заголовка")
        publish_at = datetime.fromisoformat(data["publish_at"]).strftime('%d.%m.%Y %H:%M')
        nav_buttons = []
        if index > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"nav_prev:{index}"))
        if index < len(posts) - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️ Вперёд", callback_data=f"nav_next:{index}"))
        control_buttons = [
            InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"force_pub:{index}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_post:{index}")
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [*control_buttons],
            nav_buttons if nav_buttons else []
        ])
        await bot.send_message(
            chat_id,
            f"<b>{title}</b>\n🕒 {publish_at}\n📄 Пост {index + 1} из {len(posts)}",
            reply_markup=kb
        )
    except Exception as e:
        print(f"Ошибка в send_post_preview: {e}")

@dp.callback_query(F.data.startswith("nav_"))
async def navigate_posts(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    posts = data.get("scheduled_posts")
    if not posts:
        await callback.message.edit_text("⛔️ Нет данных.")
        return
    action, raw_index = callback.data.split(":")
    index = int(raw_index)
    new_index = index - 1 if action == "nav_prev" else index + 1
    await state.update_data(current_index=new_index)
    await callback.message.delete()
    await send_post_preview(callback.message.chat.id, posts, new_index)

@dp.callback_query(F.data.startswith("del_post:"))
async def delete_scheduled(callback: types.CallbackQuery, state: FSMContext):
    index = int(callback.data.split(":")[1])
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if index >= len(lines):
        await callback.message.edit_text("❗ Элемент уже удалён.")
        return
    del lines[index]
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    await state.update_data(scheduled_posts=lines, current_index=min(index, len(lines)-1))
    await callback.message.edit_text("🗑 Пост удалён.")

@dp.callback_query(F.data.startswith("force_pub:"))
async def force_publish(callback: types.CallbackQuery, state: FSMContext):
    index = int(callback.data.split(":")[1])
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if index >= len(lines):
        await callback.message.answer("❗ Элемент уже обработан.")
        return
    try:
        data = json.loads(lines[index])
        await actually_send_post(data)
        del lines[index]
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
        await state.update_data(scheduled_posts=lines, current_index=min(index, len(lines)-1))
        await callback.message.edit_text("✅ Пост опубликован вручную.")
    except Exception as e:
        print("Ошибка при ручной публикации:", e)
        await callback.message.answer("⚠️ Не удалось опубликовать пост.")

@dp.callback_query(F.data == 'create_post')
async def start_posting(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Введите заголовок поста:")
    await state.set_state(PostStates.title)

@dp.message(PostStates.title)
async def set_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Введите текст поста:")
    await state.set_state(PostStates.body)

@dp.message(PostStates.body)
async def set_body(message: types.Message, state: FSMContext):
    await state.update_data(body=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить хештеги", callback_data="add_tags"),
         InlineKeyboardButton(text="❌ Без хештегов", callback_data="skip_tags")]
    ])
    await message.answer("Добавить хештеги?", reply_markup=kb)
    await state.set_state(PostStates.ask_tags)

@dp.callback_query(PostStates.ask_tags, F.data.in_(["add_tags", "skip_tags"]))
async def handle_tags_choice(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "add_tags":
        await callback.message.answer("Введите хештеги:")
        await state.set_state(PostStates.tags)
    else:
        await state.update_data(tags="")
        await ask_add_button(callback.message, state)

@dp.message(PostStates.tags)
async def set_tags(message: types.Message, state: FSMContext):
    await state.update_data(tags=message.text.strip())
    await ask_add_button(message, state)

async def ask_add_button(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="add_button"),
         InlineKeyboardButton(text="❌ Без кнопок", callback_data="skip_button")]
    ])
    await message.answer("Добавить кнопку?", reply_markup=kb)
    await state.set_state(PostStates.ask_button)

@dp.callback_query(PostStates.ask_button, F.data == 'add_button')
async def button_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название кнопки:")
    await state.set_state(PostStates.button_text)

@dp.callback_query(PostStates.ask_button, F.data == 'skip_button')
async def button_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(buttons=[])
    await ask_add_media(callback.message, state)

@dp.message(PostStates.button_text)
async def get_button_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if re.match(r'^https?://', text):
        await message.answer("❗ Это выглядит как ссылка. Введите название кнопки, а не URL.")
        return
    await state.update_data(current_button_text=text)
    await message.answer("Введите ссылку для кнопки:")
    await state.set_state(PostStates.button_url)

@dp.message(PostStates.button_url)
async def get_button_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not re.match(r'^https?://', url):
        await message.answer("❗ Введите корректную ссылку (http/https).")
        return
    data = await state.get_data()
    btn_text = data.get("current_button_text")
    buttons = data.get("buttons", [])
    buttons.append({"text": btn_text, "url": url})
    await state.update_data(buttons=buttons)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё кнопку", callback_data="add_button"),
         InlineKeyboardButton(text="✅ Достаточно", callback_data="done_buttons")]
    ])
    await message.answer("Добавить ещё одну кнопку?", reply_markup=kb)
    await state.set_state(PostStates.add_more_buttons)

@dp.callback_query(PostStates.add_more_buttons, F.data == 'add_button')
async def add_another_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название новой кнопки:")
    await state.set_state(PostStates.button_text)

@dp.callback_query(PostStates.add_more_buttons, F.data == 'done_buttons')
async def done_buttons(callback: types.CallbackQuery, state: FSMContext):
    await ask_add_media(callback.message, state)

async def ask_add_media(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Добавить медиа", callback_data="add_media"),
         InlineKeyboardButton(text="❌ Без медиа", callback_data="skip_media")]
    ])
    await message.answer("Прикрепить медиа?", reply_markup=kb)
    await state.set_state(PostStates.ask_media)

@dp.callback_query(PostStates.ask_media, F.data == 'add_media')
async def ask_media(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришлите фото/видео/гифку.")
    await state.set_state(PostStates.media)

@dp.callback_query(PostStates.ask_media, F.data == 'skip_media')
async def skip_media(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(media_path=None, media_type=None)
    await show_preview(callback.message, state)

@dp.message(PostStates.media)
async def handle_media(message: types.Message, state: FSMContext):
    file = None
    media_type = None
    if message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        media_type = "photo"
    elif message.video:
        file = await bot.get_file(message.video.file_id)
        media_type = "video"
    elif message.animation:
        file = await bot.get_file(message.animation.file_id)
        media_type = "animation"
    else:
        await message.answer("❗ Пришлите подходящий медиафайл.")
        return
    filename = f"{MEDIA_DIR}/media_{message.from_user.id}_{file.file_unique_id}.{file.file_path.split('.')[-1]}"
    await bot.download_file(file.file_path, filename)
    await state.update_data(media_path=filename, media_type=media_type)
    await message.answer("✅ Медиа сохранено.")
    await show_preview(message, state)

async def show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    caption = f"<b>{data['title']}</b>\n\n<blockquote>{data['body']}</blockquote>"
    if data.get("tags"):
        caption += f"\n\n{data['tags']}"
    markup = None
    if data.get("buttons"):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])] for btn in data["buttons"]]
        )
    media_path = data.get("media_path")
    media_type = data.get("media_type")
    if media_path and os.path.exists(media_path):
        input_file = types.FSInputFile(media_path)
        if media_type == "photo":
            await message.answer_photo(photo=input_file, caption=caption, reply_markup=markup)
        elif media_type == "video":
            await message.answer_video(video=input_file, caption=caption, reply_markup=markup)
        elif media_type == "animation":
            await message.answer_animation(animation=input_file, caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup)

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Опубликовать", callback_data="publish")],
        [InlineKeyboardButton(text="🗑 Отменить", callback_data="cancel")],
        [InlineKeyboardButton(text="⏱ Отложить", callback_data="schedule")]
    ])
    await message.answer("Публиковать пост?", reply_markup=confirm_kb)
    await state.set_state(PostStates.confirm)

@dp.callback_query(PostStates.confirm, F.data == 'publish')
async def publish_post(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await actually_send_post(data)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='📝 Создать пост', callback_data='create_post')]])
    await callback.message.answer("✅ Пост опубликован!", reply_markup=kb)
    await state.clear()

@dp.callback_query(PostStates.confirm, F.data == 'cancel')
async def cancel_post(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Отменено. Данные очищены.")
    await state.clear()

@dp.callback_query(PostStates.confirm, F.data == 'schedule')
async def schedule_post(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Укажите дату и время в формате: 28.06.2025 12:00 (по МСК)")
    await state.set_state(PostStates.schedule_time)

@dp.message(PostStates.schedule_time)
async def set_schedule_time(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        if dt < datetime.now():
            await message.answer("❗ Время в прошлом.")
            return
        publish_at = dt.isoformat()
        data = await state.get_data()
        data['publish_at'] = publish_at
        with open(SCHEDULE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        await message.answer(f"🕒 Пост будет опубликован {dt.strftime('%d.%m.%Y в %H:%M')}")
        await state.clear()
    except ValueError:
        await message.answer("❗ Неверный формат. Пример: 28.06.2025 12:00")

async def actually_send_post(data):
    caption = f"<b>{data['title']}</b>\n\n<blockquote>{data['body']}</blockquote>"
    if data.get("tags"):
        caption += f"\n\n{data['tags']}"
    markup = None
    if data.get("buttons"):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])] for btn in data["buttons"]]
        )
    media_path = data.get("media_path")
    media_type = data.get("media_type")
    try:
        if media_path and os.path.exists(media_path):
            input_file = types.FSInputFile(media_path)
            if media_type == "photo":
                await bot.send_photo(CHANNEL_ID, photo=input_file, caption=caption, reply_markup=markup)
            elif media_type == "video":
                await bot.send_video(CHANNEL_ID, video=input_file, caption=caption, reply_markup=markup)
            elif media_type == "animation":
                await bot.send_animation(CHANNEL_ID, animation=input_file, caption=caption, reply_markup=markup)
            os.remove(media_path)
        else:
            await bot.send_message(CHANNEL_ID, caption, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка при публикации: {e}")
async def schedule_checker():
    while True:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            remaining = []
            for line in lines:
                try:
                    data = json.loads(line)
                    dt = datetime.fromisoformat(data.get("publish_at"))
                    if datetime.now() >= dt:
                        await actually_send_post(data)
                    else:
                        remaining.append(line)
                except Exception:
                    continue
            with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
                f.writelines(remaining)
        await asyncio.sleep(60)

async def actually_send_post(data):
    caption = f"<b>{data['title']}</b>\n\n<blockquote>{data['body']}</blockquote>"
    if data.get("tags"):
        caption += f"\n\n{data['tags']}"
    markup = None
    if data.get("buttons"):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])] for btn in data["buttons"]]
        )
    media_path = data.get("media_path")
    media_type = data.get("media_type")
    try:
        if media_path and os.path.exists(media_path):
            input_file = types.FSInputFile(media_path)
            if media_type == "photo":
                await bot.send_photo(CHANNEL_ID, photo=input_file, caption=caption, reply_markup=markup)
            elif media_type == "video":
                await bot.send_video(CHANNEL_ID, video=input_file, caption=caption, reply_markup=markup)
            elif media_type == "animation":
                await bot.send_animation(CHANNEL_ID, animation=input_file, caption=caption, reply_markup=markup)
            os.remove(media_path)
        else:
            await bot.send_message(CHANNEL_ID, caption, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка при публикации: {e}")

async def main():
    asyncio.create_task(schedule_checker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())