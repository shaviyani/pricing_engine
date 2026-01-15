# Pricing Engine - Minimal MVP

A simplified hotel pricing calculation system.

## Features

- **4 Models**: Season, RoomType, RatePlan, Channel
- **3-Step Calculation**: Base Rate × Season Index + Meal Supplements - Channel Discount
- **Pricing Matrix View**: See all rates across seasons, rate plans, and channels
- **Admin Interface**: Manage all data easily

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run migrations:
```bash
python manage.py migrate
```

3. Create superuser:
```bash
python manage.py createsuperuser
```

4. Load sample data:
```bash
python manage.py loaddata pricing/fixtures/sample_data.json
```

5. Run server:
```bash
python manage.py runserver
```

6. Visit:
- Home: http://localhost:8000/
- Pricing Matrix: http://localhost:8000/matrix/
- Admin: http://localhost:8000/admin/

## Sample Data Included

- **5 Seasons**: Low, Shoulder, High, Shoulder, Peak
- **1 Room Type**: Deluxe Room ($65 base rate)
- **4 Rate Plans**: Room Only, Bed & Breakfast, Half Board, Full Board
- **2 Channels**: OTA (0% discount), DIRECT (15% discount)

## Calculation Example

```
Base Rate: $65
Season Index: 1.3 (Shoulder)
= Seasonal Rate: $84.50

Meal Supplement: $6/person × 2 pax = $12
= Rate Plan Price: $96.50

Channel Discount: 15%
= Final Rate: $82.03
```
