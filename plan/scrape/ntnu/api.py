# encoding: utf-8

# This file is part of the plan timetable generator, see LICENSE for details.

import logging
import json

from plan.common.models import Course, Semester
from plan.scrape import base
from plan.scrape import fetch
from plan.scrape import ntnu
from plan.scrape import utils

TERM_MAPPING = {
    Semester.SPRING: 'Spring',
    Semester.FALL: 'Autumn',
}


def fetch_courses(semester):
    courses = fetch.json('http://www.ime.ntnu.no/api/course/-')['course']
    for course in courses:
        if not ntnu.valid_course_code(course['code']):
            logging.warning('Skipped invalid course name: %s', course['code'])
            continue

        result = fetch_course(course['code'])
        if not result:
             continue

        if semester.year < result['taughtFromYear']:
            continue

        if result['lastYearTaught'] and semester.year > result['lastYearTaught']:
            continue

        if semester.type == semester.FALL and result['taughtInAutumn']:
            yield result
        elif semester.type == semester.SPRING and result['taughtInSpring']:
            yield result


def fetch_course(code):
    code = code.lower().encode('utf-8')
    return fetch.json('http://www.ime.ntnu.no/api/course/%s' % code)['course']


def match_term(data, semester):
    return (data['year'] == semester.year and
            data['termApplies'] == TERM_MAPPING[semester.type])


def match_assessment(data, semester):
    return (data['statusCode'] == 'ORD' and
            data['realExecutionYear'] == semester.year and
            data['realExecutionTerm'] == TERM_MAPPING[semester.type])


class Courses(base.CourseScraper):
    def scrape(self):
        for course in fetch_courses(self.semester):
            yield {'code': course['code'],
                   'name': course['name'],
                   'version': course['versionCode'],
                   'points': course['credit'],
                   'url': 'http://www.ntnu.no/studier/emner/%s' % course['code']}


class Lectures(base.LectureScraper):
    def scrape(self):
        url = 'http://www.ime.ntnu.no/api/schedule/%%s/%s/%s' % (
            TERM_MAPPING[self.semester.type].lower(), self.semester.year)

        for course in Course.objects.filter(semester=self.semester).order_by('code'):
            result = fetch.json(url % course.code.encode('utf-8'))
            if not result:
                continue

            for activity in result['activity'] or []:
                for schedule in activity['activitySchedules']:
                    if 'activityDescription' not in activity:
                        logging.warning('A %s lecture does not have a type', course.code)
                        continue

                    yield {'course': course,
                           'type': activity['activityDescription'],
                           'day':  schedule['dayNumber'],
                           'start': utils.parse_time(schedule['start']),
                           'end':  utils.parse_time(schedule['end']),
                           'weeks': utils.parse_weeks(schedule['weeks'], ','),
                           'rooms': [(r['lydiaCode'], r['location'])
                                     for r in schedule.get('rooms', [])],
                           'lecturers': [s['name'] for s in activity.get('staff', [])],
                           'groups': activity.get('studyProgrammes', [])}


class Exams(base.ExamScraper):
    def scrape(self):
        # Only bother with courses that have already been loaded.
        for course in Course.objects.filter(semester=self.semester).order_by('code'):
            result = fetch_course(course.code)
            if not result:
                continue

            for exam in result.get('assessment', []):
                if not match_assessment(exam, self.semester):
                    continue

                exam_date = exam.get('date', None)
                exam_time = exam.get('appearanceTime', None)
                handout_date = exam.get('withdrawalDate', None)
                handin_date = exam.get('submissionDate', None)
                duration = exam.get('duration', None)
                combination = exam['combinationCode']
                type_code = exam['assessmentFormCode']
                type_name = exam['assessmentFormDescription']

                yield {'course': course,
                       'exam_date': utils.parse_date(handin_date or exam_date),
                       'exam_time': utils.parse_time(exam_time),
                       'combination': combination,
                       'handout_date': utils.parse_date(handout_date),
                       'type': self.exam_type(type_code, type_name),
                       'duration': duration}
