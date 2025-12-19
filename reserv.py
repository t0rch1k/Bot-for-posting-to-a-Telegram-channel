from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
import asyncio
import re
import json
from datetime import datetime, timedelta
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID
import os

# === FSM Состояния ===
class PostStates(StatesGroup):
    title = State()
    body = State()
    ask_tags = State()
    tags = State()
    ask_button = State()
    button_text = State()
    button_url = State()
    add_more_buttons = State()
    confirm = State()
    schedule_time = State()

# === Бот и диспетчер ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

SCHEDULE_FILE = "scheduled_posts.json"

# === Команды ===
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='📝 Создать пост', callback_data='create_post')]])
    await message.answer("Привет! Я бот для постинга в канал.", reply_markup=kb)

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
    await show_preview(callback.message, state)

@dp.message(PostStates.button_text)
async def get_button_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if re.match(r'^https?://', text):
        await message.answer("❗ Это выглядит как ссылка. Введите **название** кнопки, а не URL.")
        return
    await state.update_data(current_button_text=text)
    await message.answer("Введите ссылку для кнопки:")
    await state.set_state(PostStates.button_url)

@dp.message(PostStates.button_url)
async def get_button_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not re.match(r'^https?://', url):
        await message.answer("❗ Это не похоже на ссылку. Введите корректный URL начиная с http:// или https://")
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
    await show_preview(callback.message, state)

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
    await callback.message.answer("✅ Пост опубликован!")
    await state.clear()

@dp.callback_query(PostStates.confirm, F.data == 'cancel')
async def cancel_post(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Отменено. Данные очищены.")
    await state.clear()

@dp.callback_query(PostStates.confirm, F.data == 'schedule')
async def schedule_post(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Укажите дату и время в формате: 28.06.2025 13:10 (по МСК)")
    await state.set_state(PostStates.schedule_time)

@dp.message(PostStates.schedule_time)
async def set_schedule_time(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        if dt < datetime.now():
            await message.answer("❗ Время указано в прошлом. Укажите дату и время в будущем.")
            return
        publish_at = dt.isoformat()
        data = await state.get_data()
        data['publish_at'] = publish_at
        # Сохраняем в файл
        with open(SCHEDULE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        await message.answer(f"🕒 Пост будет опубликован {dt.strftime('%d.%m.%Y в %H:%M')} (по МСК).")
        await state.clear()
    except ValueError:
        await message.answer("❗ Неверный формат. Пример: 28.06.2025 13:10")

async def actually_send_post(data):
    caption = f"<b>{data['title']}</b>\n\n<blockquote>{data['body']}</blockquote>"
    if data.get("tags"):
        caption += f"\n\n{data['tags']}"

    markup = None
    if data.get("buttons"):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])] for btn in data["buttons"]]
        )

    await bot.send_message(CHANNEL_ID, caption, reply_markup=markup)

async def schedule_checker():
    while True:
        if os.path.exists(SCHEDULE_FILE):
            lines = []
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
                    # Игнорим ошибки в парсинге строки
                    continue

            with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
                f.writelines(remaining)

        await asyncio.sleep(60)

async def main():
    asyncio.create_task(schedule_checker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
