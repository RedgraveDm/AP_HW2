import os
import logging
import sys
import datetime
import re
import requests
import asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
import matplotlib.pyplot as plt


YANDEX_CLOUD_CAT_ID = os.getenv("YANDEX_CLOUD_CAT_ID")
YANDEX_KEY_ID = os.getenv("YANDEX_KEY_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")

OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not all([YANDEX_CLOUD_CAT_ID, YANDEX_KEY_ID, YANDEX_API_KEY, OPEN_WEATHER_API_KEY, BOT_TOKEN]):
    raise ValueError("Check environment variables")


class UserProfile(StatesGroup):
    weight = State()
    height = State()
    age = State()
    activity = State()
    city = State()
    gender = State()
    calorie_goal = State()


def generate_text(prompt, iam_token, folder_id, model_name="yandexgpt-lite", temperature=0.6, max_tokens=2000):
    url = f"https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    model_uri = f"gpt://{folder_id}/{model_name}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {iam_token}"
    }

    payload = {
        "modelUri": model_uri,
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": str(max_tokens)
        },
        "messages": [
            {
                "role": "user",
                "text": prompt
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        try:
            result = response.json()
            print(result["result"]["alternatives"][0]["message"]["text"])
            return result["result"]["alternatives"][0]["message"]["text"]
        except KeyError:
            raise ValueError("Unexpected response format")
    else:
        raise Exception(f"Error: {response.status_code}, {response.text}")


def extract_average_number(text):
    match_range = re.search(r'(\d+)\s*[\-–—−]\s*(\d+)', text)
    match_single = re.search(r'\b\d+\b', text)

    if match_range:
        num1, num2 = map(int, match_range.groups())
        return (num1 + num2) // 2 if num1 >= 0 and num2 >= 0 else None

    if match_single:
        num = int(match_single.group())
        return num if num >= 0 else None

    return None


def get_geolocation(city, api_key):
    url = f'http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={api_key}'
    response = requests.get(url)
    if response.status_code == 401:
        return {"error": "Invalid API key"}
    response.raise_for_status()
    response_data = response.json()
    if response_data:
        return {"lat": response_data[0]["lat"], "lon": response_data[0]["lon"]}
    return {"error": "City not found"}


def get_current_temp(lat, lon, api_key):
    url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric'
    response = requests.get(url)
    if response.status_code == 401:
        return {"error": "Invalid API key"}
    response.raise_for_status()
    data = response.json()
    return data["main"]["temp"]


def get_declension(value, forms):
    value = abs(value)
    if 11 <= value % 100 <= 19:
        return forms[2]
    last_digit = value % 10
    if last_digit == 1:
        return forms[0]
    if 2 <= last_digit <= 4:
        return forms[1]
    return forms[2]


bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(storage=MemoryStorage())
router = Router()
dispatcher.include_router(router)

users = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%b %d %I:%M:%S %p",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def reset_logs():
    while True:
        now = datetime.datetime.now()
        reset_time = datetime.datetime.combine(now.date(), datetime.time(0, 0)) + datetime.timedelta(days=1)
        sleep_seconds = (reset_time - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        for user_id in users:
            users[user_id]["logged_water"] = 0
            users[user_id]["logged_calories"] = 0
            users[user_id]["burned_calories"] = 0
            users[user_id]["additional_water_goal"] = 0
            logger.info(f'ID{user_id} -- Reset stats')


def plot_progress(user_id):
    user = users[user_id]
    weight = user["weight"]
    activity = user["activity"]
    city = user["city"]

    logged_water = user.get("logged_water", 0)

    geo = get_geolocation(city, OPEN_WEATHER_API_KEY)
    if 'error' in geo:
        temp = 20
    else:
        temp = get_current_temp(geo["lat"], geo["lon"], OPEN_WEATHER_API_KEY) or 20

    water_goal = (user.get("additional_water_goal", 0) +
                  weight * 30 + (500 * (activity // 30)))
    if temp > 25:
        water_goal += 500
    if temp > 30:
        water_goal += 1000

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].bar(["Выпито", "Цель"], [logged_water, water_goal], color=["blue", "gray"])
    axes[0].set_title("Прогресс по воде")
    axes[0].set_ylabel("мл")

    logged_calories = user.get("logged_calories", 0)
    burned_calories = user.get("burned_calories", 0)

    calorie_goal = user.get("calorie_goal", None)
    if calorie_goal is None:
        if user['gender'] == "м":
            calorie_goal = int(10 * weight + 6.25 * user['height'] - 5 * user['age'] + 5)
        else:
            calorie_goal = int(10 * weight + 6.25 * user['height'] - 5 * user['age'] - 161)
    calorie_balance = logged_calories - burned_calories

    axes[1].bar(["Потреблено", "Сожжено", "Баланс", "Цель"],
                [logged_calories, burned_calories, calorie_balance, calorie_goal],
                color=["orange", "red", "green", "blue"])
    axes[1].set_title("Прогресс по калориям")
    axes[1].set_ylabel("ккал")

    if not os.path.isdir('graphs'):
        os.mkdir('graphs')

    plt.tight_layout()
    file_path = f"graphs/progress_{user_id}.png"
    plt.savefig(file_path)
    plt.close()
    return file_path


@router.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        logger.info(f'ID{user_id} -- Bot started!')
        await message.answer("Привет! Я помогу рассчитать дневные нормы воды и калорий!\n"
                             "Напиши /set_profile, чтобы начать.")
        return

    logger.info(f'ID{user_id} -- Received: {message.text}')
    user = users[user_id]
    await message.answer("Привет! Я помогу рассчитать дневные нормы воды и калорий!\n\n"
                         f"📊 **Ваш профиль**\n"
                         f"Вес: {user['weight']} кг\n"
                         f"Рост: {user['height']} см\n"
                         f"Возраст: {user['age']} {get_declension(user['age'], ['год', 'года', 'лет'])}\n"
                         f"Активность: {user['activity']} мин/день\n"
                         f"Город: {user['city']}\n"
                         f"Пол: {'Мужской' if user['gender'] == 'м' else 'Женский'}\n" +
                         (f"Цель калорий: {user['calorie_goal']} ккал/день"
                          if 'calorie_goal' in user else ''),
                         parse_mode="Markdown")


@router.message(Command("set_profile"))
async def set_profile(message: Message, state: FSMContext):
    await message.answer("Введите ваш вес (в кг):")
    await state.set_state(UserProfile.weight)


@router.message(UserProfile.weight)
async def process_weight(message: Message, state: FSMContext):
    weight = message.text
    if not weight.isdigit() or int(weight) <= 0:
        await message.answer("Вес должен быть натуральным числом. Попробуйте снова.")
        return
    await state.update_data(weight=int(weight))
    await message.answer("Введите ваш рост (в см):")
    await state.set_state(UserProfile.height)


@router.message(UserProfile.height)
async def process_height(message: Message, state: FSMContext):
    height = message.text
    if not height.isdigit() or int(height) <= 0:
        await message.answer("Рост должен быть натуральным числом. Попробуйте снова.")
        return
    await state.update_data(height=int(height))
    await message.answer("Введите ваш возраст:")
    await state.set_state(UserProfile.age)


@router.message(UserProfile.age)
async def process_age(message: Message, state: FSMContext):
    age = message.text
    if not age.isdigit() or int(age) <= 0:
        await message.answer("Возраст должен быть натуральным числом. Попробуйте снова.")
        return
    await state.update_data(age=int(age))
    await message.answer("Сколько минут активности у вас в день?")
    await state.set_state(UserProfile.activity)


@router.message(UserProfile.activity)
async def process_activity(message: Message, state: FSMContext):
    activity = message.text
    if not activity.isdigit() or int(activity) < 0:
        await message.answer("Активность должна быть целым неотрицательным числом. Попробуйте снова.")
        return
    await state.update_data(activity=int(activity))
    await message.answer("В каком городе вы находитесь?")
    await state.set_state(UserProfile.city)


@router.message(UserProfile.city)
async def process_city(message: Message, state: FSMContext):
    city = message.text
    geo = get_geolocation(city, OPEN_WEATHER_API_KEY)
    if 'error' in geo:
        await message.answer('Ошибка при поиске города: ' + geo['error'])
        return
    await state.update_data(city=city)
    await message.answer("Какой у вас пол? (м/ж)")
    await state.set_state(UserProfile.gender)


@router.message(UserProfile.gender)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.lower()
    if gender not in ["м", "ж"]:
        await message.answer("Введите 'м' для мужского или 'ж' для женского пола.")
        return
    await state.update_data(gender=gender)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Рассчитывать автоматически")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Введите вашу цель по калориям (или выберите автоматический расчет):",
                         reply_markup=keyboard)
    await state.set_state(UserProfile.calorie_goal)


@router.message(UserProfile.calorie_goal)
async def process_calorie_goal(message: Message, state: FSMContext):
    user_data = await state.get_data()

    weight = user_data["weight"]
    height = user_data["height"]
    age = user_data["age"]
    activity = user_data["activity"]
    city = user_data["city"]
    gender = user_data["gender"]

    if message.text == "Рассчитывать автоматически":
        if gender == "м":
            calorie_goal = int(10 * weight + 6.25 * height - 5 * age + 5)
        else:
            calorie_goal = int(10 * weight + 6.25 * height - 5 * age - 161)
    else:
        if not message.text.isdigit() or int(message.text) <= 0:
            await message.answer("Цель калорий должна быть натуральным числом. Попробуйте снова.")
            return
        calorie_goal = int(message.text)

    await state.update_data(calorie_goal=calorie_goal)
    user_id = message.from_user.id
    users[user_id] = user_data

    await state.clear()
    await message.answer(f"_Ваш профиль сохранен!_\n\n"
                         f"*Вес:* {weight} кг\n"
                         f"*Рост:* {height} см\n"
                         f"*Возраст:* {age} {get_declension(age, ['год', 'года', 'лет'])}\n"
                         f"*Активность:* {activity} мин/день\n"
                         f"*Город:* {city}\n"
                         f"*Пол:* {'Мужской' if gender == 'м' else 'Женский'}\n"
                         f"*Цель калорий:* {calorie_goal} ккал/день",
                         parse_mode="Markdown",
                         reply_markup=ReplyKeyboardRemove())


@router.message(Command("log_water"))
async def log_water(message: Message):
    user_id = message.from_user.id
    logger.info(f'ID{user_id} -- Received: {message.text}')
    if user_id not in users:
        await message.answer("Сначала настройте профиль с помощью команды /set_profile.")
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit() or int(args[1]) <= 0:
        await message.answer("Используйте формат: /log_water <количество мл (натуральное)>. "
                             "Пример: /log_water 250")
        return

    volume = int(args[1])
    users[user_id]["logged_water"] = users[user_id].get("logged_water", 0) + volume

    user = users[user_id]
    weight = user["weight"]
    activity = user["activity"]
    city = user["city"]

    geo = get_geolocation(city, OPEN_WEATHER_API_KEY)
    if 'error' in geo:
        await message.answer("Не удалось определить погоду. Цель по воде рассчитана без учета температуры.")
        temp = 20
    else:
        temp = get_current_temp(geo['lat'], geo['lon'], OPEN_WEATHER_API_KEY)
        if temp is None:
            await message.answer("Не удалось определить погоду. Цель по воде рассчитана без учета температуры.")
            temp = 20

    water_goal = (user.get("additional_water_goal", 0) +
                  weight * 30 + (500 * (activity // 30)))
    if temp > 25:
        water_goal += 500
    if temp > 30:
        water_goal += 1000
    remaining = max(water_goal - user["logged_water"], 0)

    await message.answer(f"💧 Записано: {volume} мл воды.\n"
                         f"Норма воды: {water_goal} мл (с учетом активности и температуры {temp}°C).\n"
                         f"Осталось до цели: {remaining} мл.")


@router.message(Command("log_food"))
async def log_food(message: Message, state: FSMContext):
    user_id = message.from_user.id
    logger.info(f'ID{user_id} -- Received: {message.text}')
    if user_id not in users:
        await message.answer("Сначала настройте профиль с помощью команды /set_profile.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        await message.answer("Используйте формат: /log_food <название продукта>. "
                             "Пример: /log_food банан")
        return

    product_name = args[1]

    calories_per_100g = extract_average_number(generate_text(
        f'Сколько ккал на 100г в среднем содержится в продукте: "{product_name}". '
        'Если нет точного ответа, оцени примерно. Отправь только значение числом - без пояснений и рассуждений. '
        'Не пиши никаких других чисел в ответе.',
        YANDEX_API_KEY,
        YANDEX_CLOUD_CAT_ID,
        temperature=0
    ))
    if calories_per_100g is None:
        await message.answer("Калорийность продукта не найдена.")
        return

    await state.update_data(food_name=product_name, food_calories=calories_per_100g)
    await message.answer(f"🍽 _{product_name}_: ~{calories_per_100g} ккал на 100 г.\n"
                         f"Сколько грамм вы съели/выпили?",
                         parse_mode="Markdown")
    await state.set_state("waiting_food_weight")


@router.message(StateFilter("waiting_food_weight"))
async def process_food_weight(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Введите количество граммов (натуральное число), например: 150")
        return

    data = await state.get_data()
    grams = int(message.text)
    calories = (grams / 100) * data["food_calories"]

    users[user_id]["logged_calories"] = users[user_id].get("logged_calories", 0) + calories
    await state.clear()
    await message.answer(f"✅ Записано: {calories:.1f} ккал - _{data['food_name']}_.",
                         parse_mode="Markdown")


@router.message(Command("log_workout"))
async def log_workout(message: Message):
    user_id = message.from_user.id
    logger.info(f'ID{user_id} -- Received: {message.text}')
    if user_id not in users:
        await message.answer("Сначала настройте профиль с помощью команды /set_profile.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) != 3 or not args[2].isdigit():
        await message.answer("Используйте формат: /log_workout <тип тренировки> <время в минутах>.\n"
                             "Пример: /log_workout бег 30")
        return

    workout_type, minutes = args[1].lower(), int(args[2])
    workout_calories = {
        "бег": 10,
        "ходьба": 5,
        "велосипед": 8,
        "плавание": 12
    }

    if workout_type not in workout_calories:
        await message.answer("Неизвестный тип тренировки. Доступные: бег, ходьба, велосипед, плавание.")
        return

    calories_burned = workout_calories[workout_type] * minutes
    water_needed = (minutes // 30) * 200

    users[user_id]["burned_calories"] = users[user_id].get("burned_calories", 0) + calories_burned
    users[user_id]["additional_water_goal"] = users[user_id].get("additional_water_goal", 0) + water_needed

    await message.answer(f"🏋️‍♂️ {workout_type.capitalize()} {minutes} мин — {calories_burned} ккал сожжено.\n" +
                         (f"*Дополнительно:* выпейте {water_needed} мл воды." if water_needed > 0 else ""),
                         parse_mode="Markdown")


@router.message(Command("check_progress"))
async def check_progress(message: Message):
    user_id = message.from_user.id
    logger.info(f'ID{user_id} -- Received: {message.text}')
    if user_id not in users:
        await message.answer("Сначала настройте профиль с помощью команды /set_profile.")
        return

    user = users[user_id]
    weight = user["weight"]
    activity = user["activity"]
    city = user["city"]
    logged_water = user.get("logged_water", 0)
    logged_calories = user.get("logged_calories", 0)
    burned_calories = user.get("burned_calories", 0)

    geo = get_geolocation(city, OPEN_WEATHER_API_KEY)
    if 'error' in geo:
        temp = 20
    else:
        temp = get_current_temp(geo["lat"], geo["lon"], OPEN_WEATHER_API_KEY) or 20

    water_goal = (user.get("additional_water_goal", 0) +
                  weight * 30 + (500 * (activity // 30)))
    if temp > 25:
        water_goal += 500
    if temp > 30:
        water_goal += 1000
    remaining_water = max(water_goal - logged_water, 0)

    calorie_goal = user.get("calorie_goal", None)
    if calorie_goal is None:
        if user['gender'] == "м":
            calorie_goal = int(10 * weight + 6.25 * user['height'] - 5 * user['age'] + 5)
        else:
            calorie_goal = int(10 * weight + 6.25 * user['height'] - 5 * user['age'] - 161)
    calorie_balance = logged_calories - burned_calories

    await message.answer(
        f"🎯 **Прогресс**:\n\n"
        f"💧 **Вода:**\n"
        f"- Выпито: {logged_water} мл из {water_goal} мл.\n"
        f"- Осталось: {remaining_water} мл.\n\n"
        f"🔥 **Калории:**\n"
        f"- Потреблено: {logged_calories} ккал из {calorie_goal} ккал.\n"
        f"- Сожжено: {burned_calories} ккал.\n"
        f"- Баланс: {calorie_balance} ккал.",
        parse_mode="Markdown"
    )


@router.message(Command("progress_graphs"))
async def send_progress_graphs(message: Message):
    user_id = message.from_user.id
    logger.info(f'ID{user_id} -- Received: {message.text}')
    if user_id not in users:
        await message.answer("Сначала настройте профиль с помощью команды /set_profile.")
        return

    graph_path = plot_progress(user_id)
    photo = FSInputFile(graph_path)
    await message.answer_photo(photo, caption="📊 Ваш прогресс по воде и калориям")


async def main():
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
