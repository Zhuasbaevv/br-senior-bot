import asyncio
import math
import requests
import io


def get_ip_info(ip):
    try:
        # Тянем данные: статус, страна, город, провайдер, AS, прокси, хостинг, координаты, сам IP
        res = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,country,city,isp,as,proxy,hosting,lat,lon,query",
            timeout=5,
        )
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None


async def handle_ip(message) -> None:
    """Точку входа handlers/ip_command.py ищет именно по этому имени
    (getattr(ip_module, 'handle_ip')) — раньше здесь была process_ip_comparison(message, bot, _),
    из-за чего /ip всегда падал с 'функция handle_ip не найдена'. bot берём из message.bot,
    а не из отдельного параметра — ip_command.py вызывает handler(message) без bot."""
    bot = message.bot
    args = message.text.split()
    if len(args) < 3:
        await message.answer("🚨 <b>Использование:</b> /ip [IP1] [IP2]", parse_mode="HTML")
        return

    await bot.send_chat_action(message.chat.id, "upload_photo")

    d1 = await asyncio.to_thread(get_ip_info, args[1])
    d2 = await asyncio.to_thread(get_ip_info, args[2])

    if not d1 or d1.get("status") == "fail" or not d2 or d2.get("status") == "fail":
        await message.answer("❌ <b>Ошибка:</b> проверьте IP-адреса (возможно, один из них не существует).")
        return

    # Подготовка координат (чистим от возможных проблем с форматом)
    lon1, lat1 = str(d1["lon"]).replace(",", "."), str(d1["lat"]).replace(",", ".")
    lon2, lat2 = str(d2["lon"]).replace(",", "."), str(d2["lat"]).replace(",", ".")

    # Расчет расстояния (Гаверсинус)
    r_lat1, r_lon1 = math.radians(d1["lat"]), math.radians(d1["lon"])
    r_lat2, r_lon2 = math.radians(d2["lat"]), math.radians(d2["lon"])
    dist = round(
        6371 * 2 * math.asin(math.sqrt(
            math.sin((r_lat2 - r_lat1) / 2) ** 2
            + math.cos(r_lat1) * math.cos(r_lat2) * math.sin((r_lon2 - r_lon1) / 2) ** 2
        ))
    )
    dist_fmt = f"{dist:,}".replace(",", " ")

    # Полная информация в твоем стиле
    caption = (
        f"<b>IP 1:</b> <a href='http://{d1['query']}'>{d1['query']}</a>\n"
        f"Страна: {d1.get('country', '??')}\n"
        f"Город: {d1.get('city', '??')}\n\n"
        f"<b>Информация о провайдере:</b>\n\n"
        f"Провайдер: {d1.get('isp', '??')}\n"
        f"Доп.инфа: {d1.get('as', '??')}\n"
        f"VPN: {'Detected' if (d1.get('proxy') or d1.get('hosting')) else 'None'}\n"
        f"————————————————\n"
        f"<b>IP 2:</b> <a href='http://{d2['query']}'>{d2['query']}</a>\n"
        f"Страна: {d2.get('country', '??')}\n"
        f"Город: {d2.get('city', '??')}\n\n"
        f"<b>Информация о провайдере:</b>\n\n"
        f"Провайдер: {d2.get('isp', '??')}\n"
        f"Доп.инфа: {d2.get('as', '??')}\n"
        f"VPN: {'Detected' if (d2.get('proxy') or d2.get('hosting')) else 'None'}\n\n"
        f"Расстояние между двумя IP: <b>{dist_fmt} km</b>"
    )

    # URL для Яндекс.Карт (pt = lon,lat)
    # pm2rdm - красная точка (IP 1), pm2gnm - зеленая точка (IP 2)
    map_url = f"https://static-maps.yandex.ru/1.x/?l=map&size=600,450&pt={lon1},{lat1},pm2rdm~{lon2},{lat2},pm2gnm"

    try:
        # Скачиваем карту и отправляем как файл
        headers = {"User-Agent": "Mozilla/5.0"}
        response = await asyncio.to_thread(requests.get, map_url, headers=headers, timeout=12)

        if response.status_code == 200:
            photo = io.BytesIO(response.content)
            photo.name = "map.png"
            await bot.send_photo(message.chat.id, photo, caption=caption, parse_mode="HTML")
        else:
            # Если Яндекс выдал ошибку, пробуем отправить без меток (ll=центр)
            simple_url = f"https://static-maps.yandex.ru/1.x/?l=map&size=600,450&ll={lon1},{lat1}&z=3"
            await bot.send_photo(message.chat.id, simple_url, caption=caption, parse_mode="HTML")
    except Exception:
        # Если совсем беда с сетью — шлем текст
        await bot.send_message(
            message.chat.id,
            caption + "\n\n⚠️ <i>Картинка не прогрузилась, но данные выше.</i>",
            parse_mode="HTML",
        )
