'''
Copyright 2017-present, Airbnb Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''
import json
import logging

from collections import OrderedDict

from stream_alert.alert_processor.outputs import get_output_dispatcher

logging.basicConfig()
LOGGER = logging.getLogger('StreamAlertOutput')
LOGGER.setLevel(logging.DEBUG)


def handler(event, context):
    """StreamAlert Alert Processor

    Args:
        event [dict]: contains a 'Records' top level key that holds
            all of the records for this event. Each record dict then
            contains a 'Message' key pointing to the alert payload that
            has been sent from the main StreamAlert Rule processor function
        context [AWSLambdaContext]: basically a namedtuple of properties from AWS

    Returns:
        [generator] yields back the current status to the caller
    """
    # A failure to load the config will log the error in load_output_config
    # and return here
    config = _load_output_config()
    if not config:
        return

    region = context.invoked_function_arn.split(':')[3]
    function_name = context.function_name

    # Yield back the current status to the caller
    for status in run(event, region, function_name, config):
        yield status


def run(alert, region, function_name, config):
    """Send an Alert to its described outputs.

    Args:
        alert [dict]: dictionary representating an alert with the
            following structure:

            {
                'record': record,
                'metadata': {
                    'rule_name': rule.rule_name,
                    'rule_description': rule.rule_function.__doc__,
                    'log': str(payload.log_source),
                    'outputs': rule.outputs,
                    'type': payload.type,
                    'source': {
                        'service': payload.service,
                        'entity': payload.entity
                    }
                }
            }

        region [string]: the AWS region being used
        function_name [string]: the name of the lambda function
        config [dict]: the loaded configuration for outputs from conf/outputs.json

    Returns:
        [generator] yields back dispatch status and name of the output to the handler
    """
    LOGGER.debug('Sending alert to outputs:\n%s', json.dumps(alert, indent=2))
    rule_name = alert['metadata']['rule_name']

    # strip out unnecessary keys and sort
    alert = _sort_dict(alert)

    outputs = alert['metadata']['outputs']
    # Get the output configuration for this rule and send the alert to each
    for output in set(outputs):
        try:
            service, descriptor = output.split(':')
        except ValueError:
            LOGGER.error('Improperly formatted output [%s]. Outputs for rules must '
                         'be declared with both a service and a descriptor for the '
                         'integration (ie: \'slack:my_channel\')', output)
            continue

        if not service in config or not descriptor in config[service]:
            LOGGER.error('The output \'%s\' does not exist!', output)
            continue

        # Retrieve the proper class to handle dispatching the alerts of this services
        output_dispatcher = get_output_dispatcher(service, region, function_name, config)

        if not output_dispatcher:
            continue

        LOGGER.debug('Sending alert to %s:%s', service, descriptor)

        sent = False
        try:
            sent = output_dispatcher.dispatch(descriptor=descriptor,
                                              rule_name=rule_name,
                                              alert=alert)

        except Exception as err:
            LOGGER.exception('An error occurred while sending alert '
                             'to %s:%s: %s. alert:\n%s', service, descriptor,
                             err, json.dumps(alert, indent=2))

        # Yield back the result to the handler
        yield sent, output


def _sort_dict(unordered_dict):
    """Recursively sort a dictionary

    Args:
        unordered_dict [dict]: an alert dictionary

    Returns:
        [OrderedDict] a sorted version of the dictionary
    """
    result = OrderedDict()
    for key, value in sorted(unordered_dict.items(), key=lambda t: t[0]):
        if isinstance(value, dict):
            result[key] = _sort_dict(value)
            continue

        result[key] = value

    return result


def _load_output_config(config_path='conf/outputs.json'):
    """Load the outputs configuration file from disk

    Returns:
        [dict] The output configuration settings
    """
    with open(config_path) as outputs:
        try:
            config = json.load(outputs)
        except ValueError:
            LOGGER.error('The conf/outputs.json file could not be loaded into json')
            return

    return config
