from django.db import models

class Product(models.Model):
    name                = models.CharField(max_length=255)
    description         = models.TextField(blank=True, null=True)
    unit_of_measurement = models.CharField(max_length=50)
    price               = models.DecimalField(max_digits=15, decimal_places=2)
    category            = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'category'], name='unique_name_category')
        ]

    def __str__(self):
        return self.name
