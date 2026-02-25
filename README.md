# Pricing Engine

A multi-organization, multi-property hotel revenue management platform built with Django.

## Features

- **Multi-Org Architecture** -- Organizations with multiple properties, each with independent pricing
- **Pricing Matrix** -- Versioned seasons, room types, rate plans, channels with modifier-based discounts
- **Dynamic Pricing** -- Occupancy-based multipliers, booking window adjustments, event uplifts
- **Date Rate Overrides** -- Calendar-based rate adjustments with priority layering
- **Reservation Import** -- Flexible column-mapping templates for Synxis, Opera, and custom PMS exports
- **Booking Analysis** -- KPI dashboards, channel mix, room type performance, monthly trends
- **Pickup Analysis** -- Booking velocity tracking, pace vs STLY, occupancy forecasting
- **Revenue Forecasting** -- Projected revenue by channel with occupancy calendar
- **Rate Lookup** -- Front-desk rate card with real-time pricing for any date
- **Agent Rate Cards** -- Unique shareable URLs per travel agent with quote builder
- **Platform Intelligence** -- MoT arrival data import, country analysis, market signals

## Setup

```bash
pip install -r requirements.txt   # or: pipenv install
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit:
- App: http://localhost:8000/
- Admin: http://localhost:8000/admin/
- Platform: http://localhost:8000/platform/

## Tech Stack

- Python 3.12+ / Django 5.x
- SQLite (development) -- swap to PostgreSQL for production
- ReportLab (PDF export), Pandas (data processing), pdfplumber (PDF import)
- Tailwind CSS + Chart.js (frontend)

## Project Structure

```
pricing/              Main app
  models/             core, pricing, analytics, forecasts
  views/              core, pricing, analytics, forecasts, admin_views, mixins
  services/           pricing_service, analytics_service, forecast_service, version_service
  admin/              core, pricing, analytics, forecasts, overrides, modifiers, versions
  templates/          core, manage, pricing_pages, analytics, forecasts, rates, partials
  urls/               core, pricing, analytics, forecasts, admin

platform_data/        Market intelligence (MoT arrivals, events, signals)
config/               Django settings, URLs, WSGI
```
