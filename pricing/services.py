"""
Pricing calculation services.

Three-step calculation process:
1. Base Rate × Season Index = Seasonal Rate
2. Seasonal Rate + (Meal Supplement × Occupancy) = Rate Plan Price
3. Rate Plan Price × (1 - Discount%) = Final Channel Rate
"""

from decimal import Decimal, ROUND_HALF_UP


def calculate_seasonal_rate(room_base_rate, season_index):
    """
    Step 1: Apply season index to base rate.
    
    Args:
        room_base_rate: Decimal - Base rate for the room (e.g., $65)
        season_index: Decimal - Season multiplier (e.g., 1.3)
    
    Returns:
        Decimal - Seasonal rate
    
    Example:
        calculate_seasonal_rate(Decimal('65.00'), Decimal('1.30'))
        >>> Decimal('84.50')
    """
    seasonal_rate = room_base_rate * season_index
    return seasonal_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy=2):
    """
    Step 2: Add meal supplements (default 2 people).
    
    Args:
        seasonal_rate: Decimal - Rate after season adjustment
        meal_supplement: Decimal - Meal cost per person (e.g., $6)
        occupancy: int - Number of people (default 2)
    
    Returns:
        Decimal - Rate plan price
    
    Example:
        calculate_rate_plan_price(Decimal('84.50'), Decimal('6.00'), 2)
        >>> Decimal('96.50')
    """
    meal_cost = meal_supplement * occupancy
    rate_plan_price = seasonal_rate + meal_cost
    return rate_plan_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_channel_rate(rate_plan_price, discount_percent):
    """
    Step 3: Apply channel discount.
    
    Args:
        rate_plan_price: Decimal - Rate after meals added (this is BAR)
        discount_percent: Decimal - Channel discount percentage (e.g., 15.00)
    
    Returns:
        Decimal - Final channel rate
    
    Example:
        calculate_channel_rate(Decimal('96.50'), Decimal('15.00'))
        >>> Decimal('82.03')
    """
    discount_multiplier = Decimal('1.00') - (discount_percent / Decimal('100.00'))
    channel_rate = rate_plan_price * discount_multiplier
    return channel_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_modifier_rate(channel_base_rate, modifier_discount_percent):
    """
    Step 4: Apply rate modifier discount (Genius, Mobile App, etc.).
    
    Args:
        channel_base_rate: Decimal - Rate after channel base discount
        modifier_discount_percent: Decimal - Additional modifier discount %
    
    Returns:
        Decimal - Final rate after modifier
    
    Example:
        calculate_modifier_rate(Decimal('96.50'), Decimal('10.00'))
        >>> Decimal('86.85')
    """
    discount_multiplier = Decimal('1.00') - (modifier_discount_percent / Decimal('100.00'))
    final_rate = channel_base_rate * discount_multiplier
    return final_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_final_rate(room_base_rate, season_index, meal_supplement, 
                        discount_percent, occupancy=2):
    """
    Master calculator - combines all three steps (LEGACY - for backward compatibility).
    
    Args:
        room_base_rate: Decimal - Base rate for the room
        season_index: Decimal - Season multiplier
        meal_supplement: Decimal - Meal cost per person
        discount_percent: Decimal - Channel discount percentage
        occupancy: int - Number of people (default 2)
    
    Returns:
        tuple: (final_rate, breakdown_dict)
    
    Example:
        rate, breakdown = calculate_final_rate(
            Decimal('65.00'), 
            Decimal('1.30'), 
            Decimal('6.00'), 
            Decimal('15.00'),
            2
        )
        >>> rate = Decimal('82.03')
        >>> breakdown = {
                'base_rate': Decimal('65.00'),
                'season_index': Decimal('1.30'),
                'seasonal_rate': Decimal('84.50'),
                'meal_supplement_per_person': Decimal('6.00'),
                'occupancy': 2,
                'meal_cost': Decimal('12.00'),
                'rate_plan_price': Decimal('96.50'),
                'discount_percent': Decimal('15.00'),
                'discount_amount': Decimal('14.47'),
                'final_rate': Decimal('82.03'),
            }
    """
    # Step 1: Calculate seasonal rate
    seasonal_rate = calculate_seasonal_rate(room_base_rate, season_index)
    
    # Step 2: Calculate rate plan price with meals
    meal_cost = meal_supplement * occupancy
    rate_plan_price = calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy)
    
    # Step 3: Apply channel discount
    final_rate = calculate_channel_rate(rate_plan_price, discount_percent)
    
    # Calculate discount amount
    discount_amount = rate_plan_price - final_rate
    
    # Build breakdown for display/debugging
    breakdown = {
        'base_rate': room_base_rate,
        'season_index': season_index,
        'seasonal_rate': seasonal_rate,
        'meal_supplement_per_person': meal_supplement,
        'occupancy': occupancy,
        'meal_cost': meal_cost,
        'rate_plan_price': rate_plan_price,
        'discount_percent': discount_percent,
        'discount_amount': discount_amount,
        'final_rate': final_rate,
    }
    
    return final_rate, breakdown


def calculate_final_rate_with_modifier(room_base_rate, season_index, meal_supplement, 
                                       channel_base_discount, modifier_discount=Decimal('0.00'),
                                       commission_percent=Decimal('0.00'), occupancy=2):
    """
    Enhanced calculator with BAR, channel base discount, and rate modifier support.
    
    Full Pricing Flow:
    1. Base Rate × Season Index = Seasonal Rate
    2. Seasonal Rate + Meal Supplements = BAR (Best Available Rate)
    3. BAR - Channel Base Discount = Channel Base Rate
    4. Channel Base Rate - Modifier Discount = Final Guest Rate
    5. Final Guest Rate - Commission = Net Revenue (what you actually get)
    
    Args:
        room_base_rate: Decimal - Base rate for the room
        season_index: Decimal - Season multiplier
        meal_supplement: Decimal - Meal cost per person
        channel_base_discount: Decimal - Channel's base discount from BAR
        modifier_discount: Decimal - Additional modifier discount (default 0)
        commission_percent: Decimal - Commission the channel takes (default 0)
        occupancy: int - Number of people (default 2)
    
    Returns:
        tuple: (final_rate, breakdown_dict)
    
    Example:
        # OTA Genius Member Rate
        rate, breakdown = calculate_final_rate_with_modifier(
            room_base_rate=Decimal('65.00'),
            season_index=Decimal('1.30'),
            meal_supplement=Decimal('6.00'),
            channel_base_discount=Decimal('0.00'),  # OTA has no base discount
            modifier_discount=Decimal('10.00'),     # Genius gets 10% off
            commission_percent=Decimal('18.00'),    # OTA takes 18% commission
            occupancy=2
        )
        >>> rate = Decimal('86.85')  # Guest pays this
        >>> breakdown['net_revenue'] = Decimal('71.22')  # You receive this
    """
    # Step 1: Calculate seasonal rate
    seasonal_rate = calculate_seasonal_rate(room_base_rate, season_index)
    
    # Step 2: Calculate BAR (Best Available Rate)
    meal_cost = meal_supplement * occupancy
    bar_rate = calculate_rate_plan_price(seasonal_rate, meal_supplement, occupancy)
    
    # Step 3: Apply channel base discount
    channel_base_rate = calculate_channel_rate(bar_rate, channel_base_discount)
    
    # Step 4: Apply rate modifier discount
    final_rate = calculate_modifier_rate(channel_base_rate, modifier_discount)
    
    # Step 5: Calculate net revenue (what you actually receive)
    commission_amount = final_rate * (commission_percent / Decimal('100.00'))
    net_revenue = final_rate - commission_amount
    
    # Calculate total savings from BAR
    total_discount = channel_base_discount + modifier_discount
    total_savings = bar_rate - final_rate
    
    # Build comprehensive breakdown
    breakdown = {
        # Step 1
        'base_rate': room_base_rate,
        'season_index': season_index,
        'seasonal_rate': seasonal_rate,
        
        # Step 2
        'meal_supplement_per_person': meal_supplement,
        'occupancy': occupancy,
        'meal_cost': meal_cost,
        'bar_rate': bar_rate,  # This is your BAR - the key reference rate
        
        # Step 3
        'channel_base_discount_percent': channel_base_discount,
        'channel_base_discount_amount': bar_rate - channel_base_rate,
        'channel_base_rate': channel_base_rate,
        
        # Step 4
        'modifier_discount_percent': modifier_discount,
        'modifier_discount_amount': channel_base_rate - final_rate,
        'final_rate': final_rate,  # Guest pays this
        
        # Summary
        'total_discount_percent': total_discount,
        'total_savings': total_savings,
        
        # Step 5 - Revenue
        'commission_percent': commission_percent,
        'commission_amount': commission_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        'net_revenue': net_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),  # You receive this
    }
    
    return final_rate, breakdown


def format_currency(amount, currency_symbol='$'):
    """
    Format Decimal amount as currency string.
    
    Args:
        amount: Decimal - Amount to format
        currency_symbol: str - Currency symbol (default '$')
    
    Returns:
        str - Formatted currency string
    
    Example:
        format_currency(Decimal('82.03'))
        >>> '$82.03'
    """
    return f"{currency_symbol}{amount:,.2f}"
