"""
Трекер затрат на API - отслеживание расходов на Claude и другие сервисы
"""
from datetime import datetime, timedelta


# Временное хранилище затрат (в продакшене - БД)
api_costs = []


def track_api_call(service, model, input_tokens, output_tokens, cost_usd):
    """Записать вызов API"""
    api_costs.append({
        'timestamp': datetime.now(),
        'service': service,
        'model': model,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cost_usd': cost_usd
    })


def get_costs_period(days=30):
    """Получить затраты за период"""
    if not api_costs:
        return {
            'total_calls': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cost_usd': 0,
            'by_service': {}
        }
    
    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = [c for c in api_costs if c['timestamp'] >= cutoff_date]
    
    if not filtered:
        return {
            'total_calls': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cost_usd': 0,
            'by_service': {}
        }
    
    stats = {
        'total_calls': len(filtered),
        'total_input_tokens': sum(c['input_tokens'] for c in filtered),
        'total_output_tokens': sum(c['output_tokens'] for c in filtered),
        'total_cost_usd': sum(c['cost_usd'] for c in filtered),
        'by_service': {}
    }
    
    # Группировка по сервисам
    for call in filtered:
        service = call['service']
        if service not in stats['by_service']:
            stats['by_service'][service] = {
                'calls': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'cost_usd': 0
            }
        
        stats['by_service'][service]['calls'] += 1
        stats['by_service'][service]['input_tokens'] += call['input_tokens']
        stats['by_service'][service]['output_tokens'] += call['output_tokens']
        stats['by_service'][service]['cost_usd'] += call['cost_usd']
    
    return stats


def format_costs_report(days=30):
    """Форматировать отчет о затратах"""
    stats = get_costs_period(days)
    
    if stats['total_calls'] == 0:
        return (
            f"💵 <b>ЗАТРАТЫ НА API ({days} дней)</b>\n\n"
            "📊 Данных пока нет\n\n"
            "<i>Статистика начнет собираться после первых запросов к API</i>"
        )
    
    # Конвертация USD в рубли (примерный курс)
    usd_to_rub = 95
    total_rub = stats['total_cost_usd'] * usd_to_rub
    
    text = (
        f"💵 <b>ЗАТРАТЫ НА API ({days} дней)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        f"📊 <b>ОБЩАЯ СТАТИСТИКА:</b>\n"
        f"🔢 Всего запросов: <code>{stats['total_calls']}</code>\n"
        f"📥 Входных токенов: <code>{stats['total_input_tokens']:,}</code>\n"
        f"📤 Выходных токенов: <code>{stats['total_output_tokens']:,}</code>\n"
        f"💰 Затраты: <code>${stats['total_cost_usd']:.2f}</code> (~{total_rub:.0f} ₽)\n\n"
    )
    
    # По сервисам
    if stats['by_service']:
        text += "<b>📈 ПО СЕРВИСАМ:</b>\n"
        for service, data in stats['by_service'].items():
            cost_rub = data['cost_usd'] * usd_to_rub
            text += (
                f"\n<b>{service}:</b>\n"
                f"   ├─ Запросов: {data['calls']}\n"
                f"   ├─ Токенов: {data['input_tokens'] + data['output_tokens']:,}\n"
                f"   └─ Затраты: ${data['cost_usd']:.2f} (~{cost_rub:.0f} ₽)\n"
            )
    
    return text


print("✅ utils/api_cost_tracker.py загружен")
