import datetime
import os
import json

from aiogram import Bot, Dispatcher, types, exceptions
from aiogram.utils import executor, callback_data

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import aioschedule as schedule
# 107        jobs = [asyncio.create_task(job.run()) for job in self.jobs if job.should_run]
import asyncio

from dotenv import load_dotenv

load_dotenv()

bot = Bot(token=os.getenv('TOKEN'), parse_mode=types.ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
cb_data = callback_data.CallbackData("post", "type", "value")
TEXTS = {}


def load_texts():
    """Загружает меню и тексты в память"""
    try:
        with open('texts.json') as file:
            tmp = json.load(file)
        TEXTS.clear()
        TEXTS.update(tmp)
    except json.decoder.JSONDecodeError as error:
        print(error)


async def async_load_text():
    """Просто асинхронная обертка для синхронной функции"""
    load_texts()


async def send_message_to_user(user_id: int, text: str, keyboard=None, disable_notification: bool = False) -> bool:
    """
    Отправляет сообщение пользователю и обрабатывает возможные случаи ошибки отправки
    """
    try:
        await bot.send_message(user_id, text, disable_notification=disable_notification, reply_markup=keyboard)
    except exceptions.BotBlocked:
        print(f"Target [ID:{user_id}]: blocked by user")
    except exceptions.ChatNotFound:
        print(f"Target [ID:{user_id}]: invalid user ID")
    except exceptions.RetryAfter as e:
        print(
            f"Target [ID:{user_id}]: Flood limit is exceeded. Sleep {e.timeout} seconds.")
        await asyncio.sleep(e.timeout)
        return await send_message_to_user(user_id, text, keyboard)  # Recursive call
    except exceptions.UserDeactivated:
        print(f"Target [ID:{user_id}]: user is deactivated")
    except exceptions.TelegramAPIError:
        print(f"Target [ID:{user_id}]: failed")
    else:
        print(f"Target [ID:{user_id}]: success")
        return True
    return False


async def mass_sender(users, text, timeout=.035):
    """
    Функция массовой рассылки с учетом таймаута, если слать больше 30 сообщений в секунду - забанят
    """
    print("Start sending")
    count = 0
    try:
        for user in users:
            if await send_message_to_user(user, text):
                count += 1
            await asyncio.sleep(timeout)
    finally:
        print(f"{count} messages successful sent.")


def get_button(button_info):
    """Делает инлайн кнопку"""
    data = cb_data.new(type=button_info.get('type', 'default'),
                       value=button_info.get('value', 0))
    return InlineKeyboardButton(button_info['text'],
                                url=button_info.get('url'),
                                callback_data=data)


def get_keyboard(screen):
    """Делает инлайн клавиатуру из экрана"""
    if not screen.get('button_lines'):
        return None
    keyboard = InlineKeyboardMarkup()
    for line in screen.get('button_lines'):
        keyboard.add(*[get_button(x) for x in line])
    return keyboard


async def change_screen(screen, callback_query):
    """Меняет экран пользователю - нужна для хождения по меню"""
    screen = TEXTS.get("screens", {}).get(screen)
    if not screen:
        await bot.send_message(callback_query.from_user.id, TEXTS['errors']['not_found'])
        return
    keyboard = get_keyboard(screen)
    await bot.edit_message_text(chat_id=callback_query.message.chat.id, message_id=callback_query.message.message_id, text=screen['message'], reply_markup=keyboard, disable_web_page_preview=(screen['message'].count('a href') > 1))


async def send_message(message, callback_query):
    """Отправляет сообщение пользователю после нажатия на кнопку"""
    text = TEXTS.get('messages', {}).get(message)
    if not text:
        text = TEXTS['errors']['not_found']
    await bot.send_message(callback_query.message.chat.id, text)


async def subscribe(message, callback_query):
    """Управляет подписками/отписками на напоминания"""
    with open('subscriptions.json') as file:
        subscribtions = json.load(file)
    user_id = str(callback_query.from_user.id)
    if user_id in subscribtions:
        del subscribtions[user_id]
        await bot.send_message(callback_query.from_user.id, TEXTS['messages']['unsubscribe'])
    else:
        subscribtions[user_id] = str(datetime.datetime.today())
        await bot.send_message(callback_query.from_user.id, TEXTS['messages']['subscribe'])
    with open('subscriptions.json', mode='w', encoding='utf8') as file:
        json.dump(subscribtions, file)


async def ping_users():
    """Отправляет напоминания подписанным пользователям"""
    with open('subscriptions.json') as file:
        subscribtions = json.load(file)
    users = list(subscribtions)
    await mass_sender(users, TEXTS['messages']['reminder'])


async def scheduler():
    """Добавление плановых задач"""
    schedule.every().hour.do(async_load_text)
    schedule.every(10).seconds.do(ping_users)
    while True:
        await schedule.run_pending()
        await asyncio.sleep(1)


async def on_startup(_):
    """Добавления задач при старте"""
    asyncio.create_task(scheduler())


@dp.callback_query_handler(cb_data.filter())
async def process_callback_data(callback_query: types.CallbackQuery, callback_data: dict):
    """Обработка нажатия на инлайн кнопки"""
    data = callback_data
    print(callback_query.message.chat.id)
    print(callback_query.message.from_user.id)
    type, value = data.get('type'), data.get('value')
    if type == 'change_screen':
        await change_screen(value, callback_query)
    elif type == 'send_message':
        await send_message(value, callback_query)
    elif type == 'subscribe':
        await subscribe(value, callback_query)


@dp.message_handler(commands=['start'])
async def greeting(message: types.Message):
    """Обработка команды /start"""
    print(message.chat.id)
    print(message.from_user.id)
    with open('start_users.json') as file:
        all_users = json.load(file)
    if str(message.from_user.id) not in all_users:
        all_users[str(message.from_user.id)] = str(datetime.date.today())
        with open('start_users.json', mode='w') as file:
            json.dump(all_users, file)

    screen = TEXTS.get('screens', {}).get('main_screen')
    if not screen:
        await message.answer(TEXTS['errors']['screen_not_found'])
        return
    keyboard = get_keyboard(screen)
    await message.answer(screen['message'], reply_markup=keyboard)


if __name__ == '__main__':
    load_texts()
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
