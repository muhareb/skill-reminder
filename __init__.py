# Copyright 2016 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import time
from os.path import dirname, join
from datetime import datetime, timedelta
from mycroft import MycroftSkill, intent_file_handler
from mycroft.util.parse import extract_datetime, extract_number, normalize
from mycroft.util.time import now_local, to_local, to_utc, now_utc
from mycroft.util.format import nice_time, nice_date
from mycroft.util.log import LOG
from mycroft.util import play_wav

REMINDER_PING = join(dirname(__file__), 'twoBeep.wav')

MINUTES = 60  # seconds


def deserialize(dt):
    return datetime.strptime(dt, '%Y%d%m-%H%M%S-%z')


def serialize(dt):
    return dt.strftime('%Y%d%m-%H%M%S-%z')


def is_today(d):
    return d.date() == now_local().date()


def is_tomorrow(d):
    return d.date() == now_local().date() + timedelta(days=1)


def contains_datetime(utterance, lang='en-us'):
    return extract_datetime(utterance)[1] != normalize(utterance)


def is_affirmative(utterance, lang='en-us'):
    affirmatives = ['yes', 'sure', 'please do']
    for word in affirmatives:
        if word in utterance:
            return True
    return False


class ReminderSkill(MycroftSkill):
    def __init__(self):
        super(ReminderSkill, self).__init__()
        self.notes = {}
        self.primed = False

        self.cancellable = []  # list of reminders that can be cancelled

    def initialize(self):
        # Handlers for notifications after speak
        self.add_event('speak', self.prime)
        self.add_event('mycroft.skill.handler.complete', self.notify)
        self.add_event('mycroft.skill.handler.start', self.reset)

        # Reminder checker event
        self.schedule_repeating_event(self.__check_reminder, datetime.now(),
                                      0.5 * MINUTES, name='reminder')

    def add_notification(self, identifier, note, expiry):
        self.notes[identifier] = (note, expiry)

    def prime(self, message):
        self.primed = True

    def reset(self, message):
        time.sleep(10)
        self.primed = False

    def notify(self, message):
        if self.name in message.data.get('name', ''):
            self.primed = False
            return

        handled_reminders = []
        now = now_local()
        if self.primed:
            for r in self.settings.get('reminders', []):
                print('Checking {}'.format(r))
                dt = deserialize(r[1])
                if now > dt - timedelta(minutes=10) and now < dt and \
                        r[0] not in self.cancellable:
                    handled_reminders.append(r)
                    self.speak_dialog('ByTheWay', data={'reminder': r[0]})
                    self.cancellable.append(r[0])

            self.primed = False

    def __check_reminder(self, message):
        """ Repeating event handler. Checking if a reminder time has been
            reached and presents the reminder. """
        now = now_local()
        handled_reminders = []
        for r in self.settings.get('reminders', []):
            dt = deserialize(r[1])
            if now > dt:
                play_wav(REMINDER_PING)
                self.speak(r[0])
                handled_reminders.append(r)
            if now > dt - timedelta(minutes=10):
                self.add_notification(r[0], r[0], dt)
        self.remove_handled(handled_reminders)

    def remove_handled(self, handled_reminders):
        """ The reminder is removed and rescheduled to repeat in 2 minutes.
            It is also marked as "cancellable" allowing "cancel current
             reminder" to remove it.
        """
        for r in handled_reminders:
            self.settings['reminders'].remove(r)
            new_time = deserialize(r[1]) + timedelta(minutes=2)
            self.settings['reminders'].append((r[0], serialize(new_time)))
            if r[0] not in self.cancellable:
                self.cancellable.append(r[0])

    def remove_by_name(self, name):
        for r in self.settings.get('reminders', []):
            if r[0] == name:
                break
        else:
            return False  # No matching reminders found
        self.settings['reminders'].remove(r)
        return True  # Matching reminder was found and removed

    def reschedule_by_name(self, name, new_time):
        """ Reschedule the reminder by it's name

            Arguments:
                name:       Name of reminder to reschedule.
                new_time:   New time for the reminder.

            Returns (Bool): True if a reminder was found.
        """
        serialized = serialize(new_time)
        for r in self.settings.get('reminders', []):
            if r[0] == name:
                break
        else:
            return False  # No matching reminders found
        self.settings['reminders'].remove(r)
        self.settings['reminders'].append((r[0], serialized))
        return True

    @intent_file_handler('ReminderAt.intent')
    def add_new_reminder(self, msg=None):
        """ Handler for adding  a reminder with a name at a specific time. """
        reminder = msg.data.get('reminder', None)
        if reminder is None:
            return self.add_unnamed_reminder_at(msg)

        # mogrify the response TODO: betterify!
        reminder = (' ' + reminder).replace(' my ', ' your ').strip()
        reminder = (' ' + reminder).replace(' our ', ' your ').strip()
        utterance = msg.data['utterance']
        reminder_time, rest = extract_datetime(utterance, now_local(),
                                              self.lang)

        if rest != normalize(utterance): # A datetime was extracted
            self.__save_reminder_local(reminder, reminder_time)
        else:
            self.speak_dialog('NoDateTime')

    def __save_reminder_local(self, reminder, reminder_time):
        """ Speak verification and store the reminder. """
        # Choose dialog depending on the date
        if is_today(reminder_time):
            self.speak_dialog('SavingReminder',
                              {'timedate': nice_time(reminder_time)})
        elif is_tomorrow(reminder_time):
            self.speak_dialog('SavingReminderTomorrow',
                              {'timedate': nice_time(reminder_time)})
        else:
            self.speak_dialog('SavingReminderDate',
                              {'time': nice_time(reminder_time),
                               'date': nice_date(reminder_time)})

        # Store reminder
        serialized = serialize(reminder_time)
        if 'reminders' in self.settings:
            self.settings['reminders'].append((reminder, serialized))
        else:
            self.settings['reminders'] = [(reminder, serialized)]

    def __save_unspecified_reminder(self, reminder):
        if 'unspec' in self.settings:
            self.settings['unspec'].append(reminder)
        else:
            self.settings['unspec'] = [reminder]

    @intent_file_handler('Reminder.intent')
    def add_unspecified_reminder(self, msg=None):
        """ Starts a dialog to add a reminder when no time was supplied
            for the reminder.
        """
        reminder = msg.data['reminder']
        # Handle the case where padatious misses the time/date
        if contains_datetime(msg.data['utterance']):
            return self.add_new_reminder(msg)

        response = self.get_response('ParticularTime')
        if is_affirmative(response):
            # Check if a time was also in the response
            dt, rest = extract_datetime(response)
            if rest == normalize(response):
                # No time found in the response
                response = self.get_response('SpecifyTime')
                dt, rest = extract_datetime(response)
                if rest == response:
                    self.speak('Fine, be that way')
                    return

            self.__save_reminder_local(reminder, dt)
        else:
            LOG.debug('put into general reminders')
            self.__save_unspecified_reminder(reminder)

    @intent_file_handler('UnspecifiedReminderAt.intent')
    def add_unnamed_reminder_at(self, msg=None):
        """ Handles the case where a time was given but no reminder
            name was added.
        """
        utterance = msg.data['timedate']
        reminder_time, _ = extract_datetime(utterance, now_local(), self.lang)
        response = self.get_response('AboutWhat')
        if response and reminder_time:
            self.__save_reminder_local(response, reminder_time)

    @intent_file_handler('DeleteReminderForDay.intent')
    def remove_reminders_for_day(self, msg=None):
        """ Remove all reminders for the specified date. """
        if 'date' in msg.data:
            date, _ = extract_datetime(msg.data['date'], lang=self.lang)
        else:
            date, _ = extract_datetime(msg.data['utterance'], lang=self.lang)

        if 'reminders' in self.settings:
            self.settings['reminders'] = [
                    r for r in self.settings['reminders']
                    if deserialize(r[1]).date() != date.date()]

    @intent_file_handler('GetRemindersForDay.intent')
    def get_reminders_for_day(self, msg=None):
        """ List all reminders for the specified date. """
        if 'date' in msg.data:
            date, _ = extract_datetime(msg.data['date'], lang=self.lang)
        else:
            date, _ = extract_datetime(msg.data['utterance'], lang=self.lang)

        if 'reminders' in self.settings:
            reminders = [r for r in self.settings['reminders']
                         if deserialize(r[1]).date() == date.date()]
            if len(reminders) > 0:
                for r in reminders:
                    reminder, dt = (r[0], deserialize(r[1]))
                    self.speak(reminder + ' at ' + nice_time(dt))
                return
        self.speak_dialog('NoUpcoming')

    @intent_file_handler('GetNextReminders.intent')
    def get_next_reminder(self, msg=None):
        """ Get the first upcoming reminder. """
        if 'reminders' in self.settings:
            reminders = [(r[0], deserialize(r[1]))
                         for r in self.settings['reminders']]
            next_reminder = sorted(reminders, key=lambda tup: tup[1])[0]

            if is_today(next_reminder[1]):
                self.speak_dialog('NextToday',
                                  data={'time': nice_time(next_reminder[1]),
                                        'reminder': next_reminder[0]})
            elif is_tomorrow(next_reminder[1]):
                self.speak_dialog('NextTomorrow',
                                  data={'time': nice_time(next_reminder[1]),
                                        'reminder': next_reminder[0]})
            else:
                self.speak_dialog('NextOtherDate',
                                  data={'time': nice_time(next_reminder[1]),
                                        'date': nice_date(next_reminder[1]),
                                        'reminder': next_reminder[0]})
        else:
            self.speak_dialog('NoUpcoming')


    @intent_file_handler('CancelActiveReminder.intent')
    def cancel_active(self, message):
        """ Cancel a reminder that's been triggered (and is repeating every
            2 minutes. """
        remove_list = []
        for c in self.cancellable:
            if self.remove_by_name(c):
                self.speak_dialog('ReminderRemoved')
                remove_list.append(c)
        for c in remove_list:
            self.cancellable.remove(c)

    @intent_file_handler('SnoozeReminder.intent')
    def snooze_active(self, message):
        """ Snooze the triggered reminders for 15 minutes. """
        remove_list = []
        for c in self.cancellable:
            if self.reschedule_by_name(c,
                                       now_local() + timedelta(minutes=15)):
                self.speak_dialog('RemindingInFifteen')
                remove_list.append(c)
        for c in remove_list:
            self.cancellable.remove(c)


def create_skill():
    return ReminderSkill()
