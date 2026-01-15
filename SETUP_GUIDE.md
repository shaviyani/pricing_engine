# Pricing Engine - Setup & Usage Guide

## 🎯 Project Overview

A minimal Django-based hotel pricing calculator that demonstrates the core pricing logic:

**Formula**: `Base Rate × Season Index + (Meal Supplement × 2 pax) - Channel Discount = Final Rate`

### Example Calculation (Low Season, Bed & Breakfast, DIRECT):
```
Base Rate: $65.00
× Season Index: 1.00
= Seasonal Rate: $65.00

+ Meal Supplement: $6.00/person × 2 pax = $12.00
= Rate Plan Price: $77.00

- Channel Discount: 15% = -$11.55
= FINAL RATE: $65.45
```

---

## 📁 Project Structure

```
pricing_engine/
├── manage.py
├── requirements.txt
├── db.sqlite3                    # Database (created after migration)
├── config/                       # Django settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── pricing/                      # Main app
    ├── models.py                # 4 models: Season, RoomType, RatePlan, Channel
    ├── services.py              # Calculator functions
    ├── views.py                 # Home + Matrix views
    ├── admin.py                 # Admin interface
    ├── urls.py
    ├── fixtures/
    │   └── sample_data.json     # Sample data
    ├── templates/pricing/
    │   ├── base.html
    │   ├── home.html
    │   └── matrix.html
    └── templatetags/
        └── pricing_filters.py   # Custom filters
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Migrations
```bash
python manage.py migrate
```

### 3. Load Sample Data
```bash
python manage.py loaddata pricing/fixtures/sample_data.json
```

### 4. Create Admin User (Optional)
```bash
python manage.py createsuperuser
```
Follow the prompts to create username/password.

### 5. Run Development Server
```bash
python manage.py runserver
```

### 6. Access the Application
- **Home**: http://localhost:8000/
- **Pricing Matrix**: http://localhost:8000/matrix/
- **Admin**: http://localhost:8000/admin/

---

## 📊 Sample Data Loaded

### Seasons (5 periods):
| Name | Date Range | Season Index |
|------|------------|--------------|
| Low Season | Jan 11 - Mar 30, 2026 | 1.00 |
| Shoulder Season 1 | Apr 1 - May 30, 2026 | 1.30 |
| High Season | Jun 1 - Oct 30, 2026 | 1.30 |
| Shoulder Season 2 | Nov 1 - Dec 19, 2026 | 1.10 |
| Peak Season | Dec 20, 2025 - Jan 10, 2026 | 1.20 |

### Room Types (1 room):
- **Deluxe Room**: $65.00 base rate

### Rate Plans (4 board types):
| Name | Meal Supplement (per person) |
|------|------------------------------|
| Room Only | $0.00 |
| Bed & Breakfast | $6.00 |
| Half Board | $12.00 |
| Full Board | $22.00 |

### Channels (2 booking sources):
| Name | Discount |
|------|----------|
| OTA | 0% |
| DIRECT | 15% |

---

## 💡 How to Use

### View Pricing Matrix
1. Go to http://localhost:8000/matrix/
2. Select a season from the tabs
3. View rates for all combinations
4. Hover over any rate to see calculation breakdown

### Manage Data via Admin
1. Go to http://localhost:8000/admin/
2. Login with your superuser credentials
3. Edit Seasons, Room Types, Rate Plans, or Channels
4. Changes reflect immediately in the matrix

### Add New Data

#### Add a New Season:
1. Admin → Seasons → Add Season
2. Enter name, date range, and season index
3. Save

#### Add a New Room Type:
1. Admin → Room Types → Add Room Type
2. Enter name and base rate
3. Save

#### Add a New Rate Plan:
1. Admin → Rate Plans → Add Rate Plan
2. Enter name, meal supplement, and sort order
3. Save

#### Add a New Channel:
1. Admin → Channels → Add Channel
2. Enter name, discount percentage, and sort order
3. Save

---

## 🧮 Understanding the Calculations

### Step 1: Seasonal Adjustment
```python
Seasonal Rate = Base Rate × Season Index
Example: $65.00 × 1.30 = $84.50
```

### Step 2: Add Meal Supplements
```python
Meal Cost = Meal Supplement × Occupancy (default 2 pax)
Rate Plan Price = Seasonal Rate + Meal Cost
Example: $84.50 + ($6.00 × 2) = $96.50
```

### Step 3: Apply Channel Discount
```python
Discount Multiplier = 1 - (Discount Percent / 100)
Final Rate = Rate Plan Price × Discount Multiplier
Example: $96.50 × (1 - 0.15) = $82.03
```

---

## 📝 Testing Calculations

You can test calculations in the Django shell:

```bash
python manage.py shell
```

```python
from pricing.models import Season, RoomType, RatePlan, Channel
from pricing.services import calculate_final_rate

# Get objects
season = Season.objects.get(name="High Season")
room = RoomType.objects.get(name="Deluxe Room")
plan = RatePlan.objects.get(name="Half Board")
channel = Channel.objects.get(name="OTA")

# Calculate
rate, breakdown = calculate_final_rate(
    room_base_rate=room.base_rate,
    season_index=season.season_index,
    meal_supplement=plan.meal_supplement,
    discount_percent=channel.discount_percent,
    occupancy=2
)

print(f"Final Rate: ${rate}")
print(f"Breakdown: {breakdown}")
```

---

## 🎨 Customization

### Change Currency Symbol
Edit `config/settings.py`:
```python
CURRENCY_SYMBOL = '€'  # Change from '$' to '€'
```

### Modify Occupancy Default
Edit calculations in `pricing/services.py` - change `occupancy=2` to your desired default.

### Add More Room Types
Use the admin interface or Django shell:
```python
from pricing.models import RoomType
from decimal import Decimal

RoomType.objects.create(
    name="Family Suite",
    base_rate=Decimal("120.00")
)
```

---

## 🔧 Development Notes

### Models
- **Season**: Date ranges with multiplier indices
- **RoomType**: Room categories with base rates
- **RatePlan**: Board types with meal supplements per person
- **Channel**: Booking sources with discount percentages

### Services
- `calculate_seasonal_rate()`: Step 1 calculation
- `calculate_rate_plan_price()`: Step 2 calculation
- `calculate_channel_rate()`: Step 3 calculation
- `calculate_final_rate()`: Master calculator combining all steps

### Views
- `HomeView`: Dashboard with stats and links
- `PricingMatrixView`: Main matrix display with season selector

---

## 🐛 Troubleshooting

### No data showing in matrix?
- Make sure you loaded the sample data: `python manage.py loaddata pricing/fixtures/sample_data.json`
- Check admin interface to verify data exists

### Import error?
- Ensure Django is installed: `pip install Django==5.0.1`
- Verify you're in the correct directory

### Template errors?
- Run migrations: `python manage.py migrate`
- Ensure templatetags directory exists with `__init__.py`

### Admin login not working?
- Create superuser: `python manage.py createsuperuser`

---

## 📈 Next Steps / Future Enhancements

This is a minimal MVP. Possible expansions:

1. **Multiple Occupancies**: Support different pax counts
2. **Date Range Picker**: Select custom date ranges
3. **Export Features**: Export matrix to Excel/PDF
4. **Rate Overrides**: Manual rate adjustments per date
5. **Competitor Analysis**: Compare with market rates
6. **Occupancy Forecast**: Integrate booking data
7. **API Endpoints**: RESTful API for external systems
8. **Multi-Property**: Support multiple hotels
9. **User Roles**: Different permission levels
10. **Audit Log**: Track all rate changes

---

## 📧 Support

For questions or issues, refer to:
- Django documentation: https://docs.djangoproject.com/
- Project README.md

---

**Built with Django 5.0.1 | Python 3.x | SQLite**
