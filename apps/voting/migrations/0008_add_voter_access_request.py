"""Add VoterAccessRequest model for voter self-service enrollment."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0001_initial'),
        ('voting', '0007_invitation_error_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='VoterAccessRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('email', models.EmailField(max_length=254)),
                ('message', models.TextField(blank=True, default='', help_text='Optional message from the requester.')),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                    default='pending',
                    max_length=10,
                )),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('election', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='access_requests',
                    to='elections.election',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='voteraccessrequest',
            constraint=models.UniqueConstraint(
                fields=('election', 'email'),
                name='unique_access_request_per_election',
            ),
        ),
        migrations.AddIndex(
            model_name='voteraccessrequest',
            index=models.Index(fields=['election', 'status'], name='voting_voter_election_c0bbe6_idx'),
        ),
    ]
