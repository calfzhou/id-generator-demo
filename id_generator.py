#!/usr/bin/env python3
import argparse
import datetime
import json
import random
import typing
from abc import abstractmethod
from enum import IntEnum

from fcache.cache import FileCache

APPNAME = 'com.github.calfzhou.idgen.'


class IdField:
    def __init__(self, name: str, bits: int):
        self.name = name
        self.bits = bits

    @property
    def mask(self) -> int:
        return (1 << self.bits) - 1

    @abstractmethod
    def generate(self, info: typing.Dict = None) -> typing.Union[int, str]:
        """Generate value for this field. May laverage other fields' data."""
        raise NotImplementedError

    def encode(self, value: typing.Union[int, str]) -> int:
        """Encode field data to integer."""
        return int(value)

    def decode(self, number: int) -> typing.Union[int, str]:
        """Decode field integer to user readable data."""
        return number


class DateTimeField(IdField):
    class Precision(IntEnum):
        DAY = 3600 * 24
        HOUR = 3600
        MINUTE = 60
        SECOND = 1

    DATE_TIME_FORMATS = {
        Precision.DAY: '%Y-%m-%d',
        Precision.HOUR: '%Y-%m-%d %H',
        Precision.MINUTE: '%Y-%m-%d %H:%M',
        Precision.SECOND: '%Y-%m-%d %H:%M:%S',
    }

    def __init__(self, name: str, bits: int, precision: 'DateTimeField.Precision', base: datetime.datetime):
        super().__init__(name, bits)
        self.precision = precision
        self.base = base
        self.format = self.DATE_TIME_FORMATS[self.precision]

    def generate(self, info: typing.Dict = None) -> typing.Union[int, str]:
        dt = datetime.datetime.now()
        value = dt.strftime(self.format)
        return value

    def encode(self, value: typing.Union[int, str]) -> int:
        dt = datetime.datetime.strptime(value, self.format)
        seconds = (dt - self.base).total_seconds()
        number = int(seconds / self.precision)
        return number

    def decode(self, number: int) -> typing.Union[int, str]:
        seconds = number * self.precision
        dt = self.base + datetime.timedelta(seconds=seconds)
        value = dt.strftime(self.format)
        return value


class TimeField(IdField):
    class Precision(IntEnum):
        HOUR = 3600
        MINUTE = 60
        SECOND = 1

    TIME_FORMATS = {
        Precision.HOUR: '%H',
        Precision.MINUTE: '%H:%M',
        Precision.SECOND: '%H:%M:%S',
    }

    def __init__(self, name: str, bits: int, precision: 'TimeField.Precision'):
        super().__init__(name, bits)
        self.precision = precision
        self.format: str = self.TIME_FORMATS[self.precision]

    def generate(self, info: typing.Dict = None) -> typing.Union[int, str]:
        time = datetime.datetime.now().time()
        value = time.strftime(self.format)
        return value

    def encode(self, value: typing.Union[int, str]) -> int:
        time = datetime.datetime.strptime(value, self.format).time()
        seconds = time.hour * 3600 + time.minute * 60 + time.second
        number = seconds // self.precision
        return number

    def decode(self, number: int) -> typing.Union[int, str]:
        seconds = number * self.precision
        hour, seconds = divmod(seconds, 3600)
        minute, second = divmod(seconds, 60)
        time = datetime.time(hour, minute, second)
        value = time.strftime(self.format)
        return value


class SequenceField(IdField):
    def __init__(self, name: str, bits: int,
                 start: typing.Union[int, typing.Tuple[int, int]] = 0,
                 step: typing.Union[int, typing.Tuple[int, int]] = 1,
                 keys: typing.List[str] = None, cache_name: str = None):
        super().__init__(name, bits)
        self.start: typing.Tuple[int, int] = (start, start) if isinstance(start, int) else start
        self.step: typing.Tuple[int, int] = (step, step) if isinstance(step, int) else step
        self.rand = random.Random()
        self.keys = keys
        self.cache = FileCache(APPNAME + cache_name, flag='cs') if cache_name else {}
        # print(self.cache.cache_dir)

    def generate(self, info: typing.Dict = None) -> typing.Union[int, str]:
        info = info or {}
        if self.keys:
            key = '-'.join(str(info[k]) for k in self.keys)
        else:
            key = self.name

        seq = self._next_seq(self.cache[key]) if (key in self.cache) else self._new_seq()
        self.cache[key] = seq
        return seq

    def _new_seq(self) -> int:
        return self.rand.randint(*self.start)

    def _next_seq(self, prev: int) -> int:
        return prev + self.rand.randint(*self.step)


class NumberField(IdField):
    def __init__(self, name: str, bits: int, start: int = 0, end: int = None):
        super().__init__(name, bits)
        self.start = start
        self.end = self.mask if (end is None) else end
        self.rand = random.Random()

    def generate(self, info: typing.Dict = None) -> typing.Union[int, str]:
        return self.rand.randint(self.start, self.end)

    def decode(self, number: int) -> typing.Union[int, str]:
        if not self.start <= number <= self.end:
            raise ValueError(f'field {self.name} number {number} is out of range')
        return number


class IdGenerator:
    def __init__(self, name: str, fields: typing.List[IdField]):
        self.name = name
        self.fields = fields

    def generate(self, custom_data: typing.Dict = None) -> typing.Union[int, str]:
        info = self._generate(custom_data or {})
        parts = self._encode(info)
        id_num = self._assemble(parts)
        the_id = self._format(id_num)
        return the_id

    def parse(self, the_id: typing.Union[int, str]) -> typing.Dict:
        """Parse final id to info dictionary."""
        id_num = self._parse(the_id)
        parts = self._disassemble(id_num)
        info = self._decode(parts)
        return info

    def _generate(self, custom_data: typing.Dict) -> typing.Dict:
        """Generate id key-value information. Will use given custom data."""
        info = {}
        for field in self.fields:
            if field.name in custom_data:
                info[field.name] = custom_data[field.name]
            else:
                info[field.name] = field.generate(info)

        return info

    def _encode(self, info: typing.Dict) -> typing.List[int]:
        """Encode key-value information to number components."""
        parts = [field.encode(info[field.name]) for field in self.fields]
        return parts

    def _decode(self, parts: typing.List[int]) -> typing.Dict:
        """Decode number components to key-value information."""
        info = {field.name: field.decode(parts[i]) for i, field in enumerate(self.fields)}
        return info

    def _assemble(self, parts: typing.List[int]) -> int:
        """Assemble list of number components to id number."""
        if len(parts) != len(self.fields):
            raise ValueError('the number of parts must be the same with fields')

        id_num = 0
        number: int
        field: IdField
        for number, field in zip(parts, self.fields):
            if not 0 <= number <= field.mask:
                raise ValueError(f'number {number} is out of its bits range ({field.bits} bits, 0 ~ {field.mask})')
            id_num = (id_num << field.bits) | number

        return id_num

    def _disassemble(self, id_num: int) -> typing.List[int]:
        """Disassemble id number to a list of number components."""
        parts: typing.List[int] = []
        for field in reversed(self.fields):
            number = id_num & field.mask
            parts.append(number)
            id_num >>= field.bits

        if id_num != 0:
            raise ValueError(f'the highest not used part is not 0, but {id_num}')

        return list(reversed(parts))

    def _format(self, id_num: int) -> typing.Union[int, str]:
        """Convert id number to human readable number or string."""
        return id_num

    def _parse(self, the_id: typing.Union[int, str]) -> int:
        """Parse number id from human readable number or string."""
        return int(the_id)


def get_generators() -> typing.Dict[str, IdGenerator]:
    generators = {}

    generator = IdGenerator(
        'order',
        [
            NumberField('placeholder', 1, start=1),
            DateTimeField(
                'time', 29, precision=DateTimeField.Precision.SECOND,
                base=datetime.datetime(2018, 1, 1)),
            SequenceField('sequence', 16, start=(0, 10000), step=(1, 10),
                          keys=['time'], cache_name='order')
        ]
    )
    generators[generator.name] = generator

    generator = IdGenerator(
        'order-m',
        [
            NumberField('placeholder', 1, start=1),
            DateTimeField(
                'time', 24, precision=DateTimeField.Precision.MINUTE,
                base=datetime.datetime(2018, 1, 1)),
            SequenceField('sequence', 20, start=(0, 10000), step=(1, 10),
                          keys=['time'], cache_name='order-m')
        ]
    )
    generators[generator.name] = generator

    return generators


def parse_variable_definition(text):
    parts = text.split('=', 1)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(f'unrecognized variable definition "{text}"')
    return tuple(parts)


def generate_main(generator: IdGenerator, args):
    custom_data = json.loads(args.data) if args.data else None
    for _i in range(args.n):
        the_id = generator.generate(custom_data)
        info = generator.parse(the_id)
        print(the_id, json.dumps(info))


def parse_main(generator: IdGenerator, args):
    info = generator.parse(args.the_id)
    print(args.the_id, json.dumps(info))


def main():
    generators = get_generators()

    parser = argparse.ArgumentParser(description='ID Generator and Parser')
    parser.add_argument('-c', '--category', default='order', choices=generators.keys(),
                        help='which category of ID to use (default: order)')

    subparsers = parser.add_subparsers(help='sub-command')

    parser_generate = subparsers.add_parser('generate', aliases=['g'],
                                            description='generator specified arguments',
                                            help='to generate new id(s)')
    parser_generate.add_argument('-n', type=int, default=1,
                                 help='how many ids to generate (default: 1)')
    parser_generate.add_argument('-d', '--data',
                                 help='category specified data, in json format,'
                                 ' e.g. \'{"sequence": 100}\'')
    parser_generate.set_defaults(func=generate_main)

    parser_parse = subparsers.add_parser('parse', aliases=['p'],
                                         description='parser specified arguments',
                                         help='to parse given id(s)')
    parser_parse.add_argument('the_id',
                              help='a ID to be parsed')
    parser_parse.set_defaults(func=parse_main)

    args = parser.parse_args()
    # print(args)
    if 'func' in args:
        generator = generators.get(args.category)
        args.func(generator, args)
    else:
        print('should choose a sub-command')


if __name__ == '__main__':
    main()
