# -*- coding: UTF-8 -*-

# Copyright (C) 2006 Evan Dandrea <evand@ubuntu.com>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import syslog
import sys
import os
import debconf

from ubiquity.filteredcommand import FilteredCommand

class MigrationAssistant(FilteredCommand):
    firstrun = True
    def prepare(self):
        self.err = None
        self.errors = False
        self.got_a_question = False
        self.error_list = ['migration-assistant/password-mismatch',
                           'migration-assistant/password-empty',
                           'migration-assistant/username-bad',
                           'migration-assistant/username-reserved']
        questions = ['^migration-assistant/partitions',
                     '^migration-assistant/.*/users$',
                     '^migration-assistant/.*/items$',
                     '^migration-assistant/.*/user$',
                     '^migration-assistant/.*/password$',
                     '^migration-assistant/failed-unmount',
                     '^ubiquity/run-ma-again',
                     'ERROR']
        return (['/usr/share/ubiquity/migration-assistant'], questions)


    def run(self, priority, question):
        if question != 'ubiquity/run-ma-again':
            self.got_a_question = True
        if question == 'migration-assistant/failed-unmount':
            response = self.frontend.question_dialog(
                self.description(question),
                self.extended_description(question),
                ('ubiquity/text/go_back', 'ubiquity/text/continue'))
            if response is None or response == 'ubiquity/text/continue':
                self.preseed(question, 'true')
            else:
                self.preseed(question, 'false')
            return True

        # FIXME: This is not preseed friendly.
        if self.firstrun:
            # We cannot currently import from partitions that are scheduled for
            # deletion, so we filter them out of the list.
            if question == 'migration-assistant/partitions':
                self.filter_parts()
            elif question == 'ubiquity/run-ma-again':
                if self.db.get('migration-assistant/partitions') != '':
                    self.set_choices()
                    self.firstrun = False
                    # TODO cjwatson 2007-09-22: This is a wart, but it
                    # prevents the ubiquity interface from always being
                    # shown in automatic installs.
                    # TODO evand 2007-09-24: A slight improvement over the
                    # previous wart: skip entering the GTK loop if we do not
                    # have any questions to ask.
                    if not self.got_a_question:
                        return self.succeeded
                    else:
                        return FilteredCommand.run(self, priority, question)
                else:
                    self.db.set('ubiquity/run-ma-again', 'false')

            # In order to find out what operating systems and users we're
            # dealing with we need to seed all of the questions to step through
            # ma-ask, but we cannot seed user and password with an empty string
            # because that will cause errors so we cheat and tell m-a that we
            # want to continue with the invalid data anyway.
            elif question.endswith('user'):
                self.preseed(question, 'skip-question')
            elif question.endswith('password'):
                self.preseed(question, 'skip-question')
            else:
                self.preseed(question, ", ".join(self.choices(question)))


        elif self.err:
            # As mentioned in error() we are looking for the question
            # after the error as it's what the error is associated with.
            if question.endswith('password'):
                user = question[:question.rfind('/')]
                user = user[user.rfind('/')+1:]

                self.frontend.ma_password_error(self.err, user)
                self.preseed(question, 'skip-question')
                self.err = ''

            elif question.endswith('user'):
                user = question[:question.rfind('/')]
                user = user[user.rfind('/')+1:]

                self.frontend.ma_user_error(self.err, user)
                self.preseed(question, 'skip-question')
                self.err = ''
        elif question == 'ubiquity/run-ma-again':
            if self.errors:
                return FilteredCommand.run(self, priority, question)
            self.db.set('ubiquity/run-ma-again', 'false')
        return True # False is backup

    def error(self, priority, question):
        # Because we have already seeded the questions and thus will not see
        # them in run() we have to hold onto the error until the next question
        # which will tell us what question, and thus what partition and user
        # this error is tied to.
        # This of course assumes that the next question is related to the error,
        # but that's a safe bet as I cannot think of a question we wouldn't want
        # to re-ask if an error occurred.
        if question in self.error_list:
            self.errors = True
            self.err = self.extended_description(question)
        else:
            self.frontend.error_dialog(self.description(question),
                                       self.extended_description(question))
        return FilteredCommand.error(self, priority, question)
    
    def ok_handler(self):
        choices, new_users = self.frontend.ma_get_choices()
        users = {}

        for c in choices:
            if c['selected']:
                question = 'migration-assistant/%s/%s/' % \
                    (c['part'],c['user'].replace(' ',':'))
                self.db.register('migration-assistant/items', question + 'items')
                self.preseed(question + 'items', ', '.join(c['items']))
                self.db.register('migration-assistant/user', question + 'user')
                self.preseed(question + 'user', c['newuser'])
                try:
                    users[c['part']].append(c['user'])
                except KeyError:
                    users[c['part']] = [c['user']]

        for p in users.iterkeys():
            question = 'migration-assistant/%s/users' % p
            self.db.register('migration-assistant/users', question)
            self.preseed(question, ', '.join(users[p]))

        for u in new_users.iterkeys():
            user = new_users[u]
            question = 'migration-assistant/new-user/%s/' % u

            try:
                self.db.register('migration-assistant/fullname', question + 'fullname')
                self.preseed(question + 'fullname', user['fullname'])
            except KeyError:
                self.preseed(question + 'fullname', '')
            try:
                self.db.register('migration-assistant/password', question + 'password')
                self.preseed(question + 'password', user['password'],
                             escape=True)
            except KeyError:
                self.preseed(question + 'password', '')
            try:
                self.db.register('migration-assistant/password-again', question + 'password-again')
                self.preseed(question + 'password-again', user['confirm'],
                             escape=True)
            except KeyError:
                self.preseed(question + 'password-again', '')

        self.errors = None
        self.db.set('ubiquity/run-ma-again', 'true')
        FilteredCommand.ok_handler(self)
        #self.db.shutdown()
        #self.run_command()

    def filter_parts(self):
        question = 'migration-assistant/partitions'
        from ubiquity.parted_server import PartedServer
        parted = PartedServer()

        parts = []
        for disk in parted.disks():
            parted.select_disk(disk)
            for partition in parted.partitions():
                # We check to see if the partition is scheduled to be
                # formatted and if not add it to the list of post-commit
                # available partitions.
                filename = '/var/lib/partman/devices/%s/%s/view' % \
                    (disk, partition[1])
                fd = open(filename)
                pieces = fd.readline().rstrip('\n').split(None, 8)
                fd.close()
                line = [''] * 8
                line[0:len(pieces)] = pieces
                formatted = ['F', 'f', 'swap']
                if line[5] not in formatted:
                    if line[4] not in formatted:
                        parts.append(partition[5])

        ret = []
        for choice in self.choices(question):
            if choice[choice.rfind('(')+1:choice.rfind(')')] in parts:
                ret.append(choice)

                self.preseed(question, ", ".join(ret))

    def set_choices(self):
        tree = []
        systems = self.db.get('migration-assistant/partitions')
        if systems:
            systems = systems.split(', ')
            try:
                ret = []
                for os in systems:
                    osref = os
                    part = os[os.rfind('/')+1:-1] # hda1
                    os = os[:os.rfind('(')-1]

                    users = self.db.get('migration-assistant/' + part + '/users')
                    if not users:
                        syslog.syslog('migration-assistant: filtering out %s' \
                            ' as it has no users' % osref)
                        continue
                    else:
                        ret.append(osref)

                    users = users.split(', ')
                    for user in users:
                        items = self.db.get('migration-assistant/' + part + '/' + \
                            user.replace(' ', ':') + '/items')
                        # If there are no items to import for the user, there's no sense
                        # in showing it.  It might make more sense to move this check
                        # into ma-ask.
                        if items:
                            items = items.split(', ')
                            tree.append({'user': user,
                                         'part': part,
                                         'os': os,
                                         'newuser': '',
                                         'items': items,
                                         'selected': False})
                    # We now unset everything as the checkboxes will be unselected
                    # by default and debconf needs to match that.
                    self.db.set('migration-assistant/%s/users' % part, '')
                # Prune out partitions that do not have any users.
                self.db.set('migration-assistant/partitions', ", ".join(ret))
            except debconf.DebconfError, e:
                for line in str(e).split('\n'):
                    syslog.syslog(syslog.LOG_ERR, line)
                self.db.set('migration-assistant/partitions', '')
                tree = []

        self.frontend.ma_set_choices(tree)

# vim:ai:et:sts=4:tw=80:sw=4:
