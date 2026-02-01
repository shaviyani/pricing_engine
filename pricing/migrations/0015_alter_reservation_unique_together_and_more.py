from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pricing', '0014_alter_reservation_unique_together_and_more'),  # UPDATE THIS to your last migration
    ]

    operations = [
        # Step 1: Remove the old unique constraint
        migrations.AlterUniqueTogether(
            name='reservation',
            unique_together=set(),
        ),
        
        # Step 2: Add the new unique constraint with arrival_date
        migrations.AlterUniqueTogether(
            name='reservation',
            unique_together={('hotel', 'confirmation_no', 'arrival_date', 'room_sequence')},
        ),
    ]