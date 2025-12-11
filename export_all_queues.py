import requests
import json
import csv
import os
import sys

# ============= КОНФІГУРАЦІЯ З СІКРЕТІВ =============
API_BASE_URL = os.environ.get('API_BASE_URL')
TIMEOUT = 10
MAX_RETRIES = 3

class QueueExporter:
    def __init__(self):
        self.all_queues = []
        self.errors = []
    
    def validate_config(self):
        """Перевірити що API_BASE_URL встановлено"""
        if not API_BASE_URL:
            print("❌ ПОМИЛКА: API_BASE_URL не встановлено в secrets!")
            print("💡 Додай у GitHub Settings → Secrets and variables → Actions:")
            print("   API_BASE_URL = https://www.ztoe.com.ua/gpv/api/")
            return False
        
        print(f"✅ API_BASE_URL встановлено")
        return True
        
    def get_rems(self):
        """Отримати всі РЕМи з обробкою помилок"""
        try:
            print("📍 Завантажую РЕМи...")
            response = requests.get(f"{API_BASE_URL}api-rem.php", timeout=TIMEOUT)
            response.raise_for_status()
            rems = response.json()
            
            if not rems:
                print("⚠️ РЕМи не знайдені (пуста відповідь)")
                return []
            
            rems_list = rems if isinstance(rems, list) else [rems]
            print(f"✅ Завантажено {len(rems_list)} РЕМів")
            return rems_list
        except requests.exceptions.Timeout:
            self.errors.append("❌ ТАЙМАУТ: api-rem.php")
            print("❌ Таймаут при завантаженні РЕМів")
            return []
        except requests.exceptions.RequestException as e:
            self.errors.append(f"❌ Помилка запиту РЕМів: {e}")
            print(f"❌ Помилка: {e}")
            return []
        except json.JSONDecodeError:
            self.errors.append("❌ Помилка парсингу JSON РЕМів")
            print("❌ Помилка парсингу JSON")
            return []
    
    def get_cities(self, rem_id):
        """Отримати міста з повторами при помилці"""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    f"{API_BASE_URL}api-city.php?rem_id={rem_id}", 
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                cities = response.json()
                
                if not cities:
                    return []
                
                return cities if isinstance(cities, list) else [cities]
            except requests.exceptions.Timeout:
                if attempt == MAX_RETRIES - 1:
                    self.errors.append(f"⚠️ ТАЙМАУТ: cities для rem_id={rem_id}")
                continue
            except Exception:
                if attempt == MAX_RETRIES - 1:
                    self.errors.append(f"⚠️ Помилка cities для rem_id={rem_id}")
                continue
        
        return []
    
    def get_streets(self, city_id):
        """Отримати вулиці з повторами"""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    f"{API_BASE_URL}api-street.php?city_id={city_id}", 
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                streets = response.json()
                
                if not streets:
                    return []
                
                return streets if isinstance(streets, list) else [streets]
            except:
                if attempt == MAX_RETRIES - 1:
                    self.errors.append(f"⚠️ Помилка streets для city_id={city_id}")
                continue
        
        return []
    
    def get_addresses(self, street_id):
        """Отримати адреси з повторами"""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    f"{API_BASE_URL}api-address.php?street_id={street_id}", 
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                addresses = response.json()
                
                if not addresses:
                    return []
                
                return addresses if isinstance(addresses, list) else [addresses]
            except:
                if attempt == MAX_RETRIES - 1:
                    self.errors.append(f"⚠️ Помилка addresses для street_id={street_id}")
                continue
        
        return []
    
    def export_all(self):
        """Вивантажити ВСІ чергі та адреси"""
        print("=" * 70)
        print("🔍 ВИВАНТАЖЕННЯ ВСІХ ЧЕРГ ТА АДРЕС")
        print("=" * 70)
        
        rems = self.get_rems()
        if not rems:
            print("❌ Не вдалося завантажити РЕМи. Вихід.")
            return []
        
        total_addresses = 0
        processed_rems = 0
        
        for rem_idx, rem in enumerate(rems, 1):
            try:
                rem_id = rem.get('id', rem.get('cherga_id'))
                rem_name = rem.get('name', rem.get('title', f'РЕМ {rem_id}'))
                
                if not rem_id:
                    self.errors.append(f"⚠️ РЕМ без ID: {rem_name}")
                    continue
                
                print(f"\n📌 РЕМ {rem_idx}/{len(rems)}: {rem_name} (ID: {rem_id})")
                processed_rems += 1
                
                cities = self.get_cities(rem_id)
                if not cities:
                    print(f"   ⚠️ Міст не знайдено")
                    continue
                
                print(f"   └─ 🏙️ Міст: {len(cities)}")
                
                for city in cities:
                    try:
                        city_id = city.get('id', city.get('city_id'))
                        city_name = city.get('name', city.get('title', f'Місто {city_id}'))
                        
                        if not city_id:
                            continue
                        
                        streets = self.get_streets(city_id)
                        if not streets:
                            continue
                        
                        print(f"      └─ 🛣️  {city_name}: {len(streets)} вулиць")
                        
                        for street in streets:
                            try:
                                street_id = street.get('id', street.get('street_id'))
                                street_name = street.get('name', street.get('title', f'Вулиця {street_id}'))
                                
                                if not street_id:
                                    continue
                                
                                addresses = self.get_addresses(street_id)
                                if not addresses:
                                    continue
                                
                                for addr in addresses:
                                    try:
                                        queue_id = addr.get('cherga_id', addr.get('queue_id'))
                                        subqueue_id = addr.get('pidcherga_id', addr.get('subqueue_id'))
                                        addr_name = addr.get('name', addr.get('title', 'Unknown'))
                                        
                                        if not queue_id or not subqueue_id:
                                            continue
                                        
                                        queue_data = {
                                            'rem_id': rem_id,
                                            'rem_name': rem_name,
                                            'city_id': city_id,
                                            'city_name': city_name,
                                            'street_id': street_id,
                                            'street_name': street_name,
                                            'address_id': addr.get('id'),
                                            'address_name': addr_name,
                                            'queue_id': queue_id,
                                            'subqueue_id': subqueue_id,
                                            'full_address': f"{rem_name}, {city_name}, вул. {street_name}, {addr_name}"
                                        }
                                        
                                        # Перевірка дублікатів
                                        if not any(q['queue_id'] == queue_id and q['subqueue_id'] == subqueue_id for q in self.all_queues):
                                            self.all_queues.append(queue_data)
                                            total_addresses += 1
                                        
                                        if total_addresses % 100 == 0:
                                            print(f"         ✓ Завантажено {total_addresses} адрес...")
                                    except Exception as e:
                                        self.errors.append(f"⚠️ Помилка адреси: {e}")
                                        continue
                            except Exception as e:
                                self.errors.append(f"⚠️ Помилка вулиці: {e}")
                                continue
                    except Exception as e:
                        self.errors.append(f"⚠️ Помилка міста: {e}")
                        continue
            except Exception as e:
                self.errors.append(f"⚠️ Помилка РЕМу: {e}")
                continue
        
        print("\n" + "=" * 70)
        print(f"✅ ЗАВЕРШЕНО!")
        print(f"   • РЕМів оброблено: {processed_rems}/{len(rems)}")
        print(f"   • Адрес завантажено: {total_addresses}")
        print(f"   • Помилок: {len(self.errors)}")
        print("=" * 70)
        
        if self.errors:
            print("\n⚠️ ПОМИЛКИ (перші 10):")
            for error in self.errors[:10]:
                print(f"   {error}")
        
        return self.all_queues
    
    def save_json(self, filename='all_queues.json'):
        """Зберегти у JSON"""
        if not self.all_queues:
            print("❌ Немає даних для збереження")
            return False
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.all_queues, f, indent=2, ensure_ascii=False)
            print(f"💾 JSON збережено: {filename} ({len(self.all_queues)} записів)")
            return True
        except Exception as e:
            print(f"❌ Помилка збереження JSON: {e}")
            return False
    
    def save_csv(self, filename='all_queues.csv'):
        """Зберегти у CSV"""
        if not self.all_queues:
            print("❌ Немає даних для збереження")
            return False
        
        try:
            keys = self.all_queues[0].keys()
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(self.all_queues)
            print(f"💾 CSV збережено: {filename} ({len(self.all_queues)} записів)")
            return True
        except Exception as e:
            print(f"❌ Помилка збереження CSV: {e}")
            return False
    
    def print_summary(self):
        """Показати статистику"""
        if not self.all_queues:
            print("❌ Немає даних для статистики")
            return
        
        print("\n" + "=" * 70)
        print("📊 СТАТИСТИКА")
        print("=" * 70)
        
        rems = set(q['rem_name'] for q in self.all_queues)
        cities = set(q['city_name'] for q in self.all_queues)
        streets = set(q['street_name'] for q in self.all_queues)
        
        print(f"🏘️  РЕМів: {len(rems)}")
        print(f"🏙️  Міст: {len(cities)}")
        print(f"🛣️  Вулиць: {len(streets)}")
        print(f"🏠 Адрес (черг): {len(self.all_queues)}")
        print("=" * 70)
        
        print("\n📋 ПРИКЛАД ПЕРШИХ 5 ЗАПИСІВ:\n")
        for i, q in enumerate(self.all_queues[:5], 1):
            print(f"{i}. {q['full_address']}")
            print(f"   QUEUE_ID={q['queue_id']}, SUBQUEUE_ID={q['subqueue_id']}\n")

def main():
    """Головна функція"""
    try:
        exporter = QueueExporter()
        
        # Валідація
        if not exporter.validate_config():
            return 1
        
        queues = exporter.export_all()
        
        if queues:
            exporter.save_json('all_queues.json')
            exporter.save_csv('all_queues.csv')
            exporter.print_summary()
            print("\n✅ Експорт завершено успішно!")
            return 0
        else:
            print("\n❌ Не вдалося експортувати дані")
            return 1
    except KeyboardInterrupt:
        print("\n\n⛔ Перервано користувачем")
        return 1
    except Exception as e:
        print(f"\n❌ Критична помилка: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
