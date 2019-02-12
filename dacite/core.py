import copy
from dataclasses import fields, is_dataclass
from typing import TypeVar, Type, Optional, get_type_hints, Mapping, Any

from dacite.config import Config, CanNotFindValue
from dacite.data import Data
from dacite.dataclasses import get_default_value_for_field, create_instance
from dacite.exceptions import ForwardReferenceError, WrongTypeError, DaciteError
from dacite.types import extract_origin_collection, is_instance, \
    is_generic_collection, is_union, extract_generic, is_optional

T = TypeVar('T')


def from_dict(data_class: Type[T], data: Data, config: Optional[Config] = None) -> T:
    """Create a data class instance from a dictionary.

    :param data_class: a data class type
    :param data: a dictionary of a input data
    :param config: a configuration of the creation process
    :return: an instance of a data class
    """
    init_values: Data = {}
    post_init_values: Data = {}
    config = config or Config()
    config.validate(data_class, data)
    try:
        data_class_hints = get_type_hints(data_class, globalns=config.forward_references)
    except NameError as error:
        raise ForwardReferenceError(str(error))
    for field in fields(data_class):
        field = copy.copy(field)
        field.type = data_class_hints[field.name]
        try:
            value = _build_value(
                type=field.type,
                data=config.get_value(field, data),
                config=config.make_inner(field),
            )
            if not is_instance(value, field.type):
                raise WrongTypeError(field.name, field.type, value)
        except CanNotFindValue:
            value = get_default_value_for_field(field)
        if field.init:
            init_values[field.name] = value
        else:
            post_init_values[field.name] = value

    return create_instance(
        data_class=data_class,
        init_values=init_values,
        post_init_values=post_init_values,
    )


def _build_value(type: Type, data: Any, config: Config) -> Any:
    if is_union(type):
        return _build_value_for_union(
            type=type,
            data=data,
            config=config,
        )
    elif is_generic_collection(type) and is_instance(data, type):
        return _build_value_for_collection(
            collection=type,
            data=data,
            config=config,
        )
    elif is_dataclass(type) and is_instance(data, Data):
        return _build_value_for_dataclass(
            data_class=type,
            data=data,
            config=config,
        )
    return data


def _build_value_for_union(type: Type, data: Any, config: Config) -> Any:
    for inner_type in extract_generic(type):
        try:
            value = _build_value(
                type=inner_type,
                data=data,
                config=config,
            )
            if is_instance(value, inner_type):
                return value
        except DaciteError as e:
            if is_optional(type) and len(extract_generic(type)) == 2:
                raise e
    else:
        raise WrongTypeError('', type, data)


def _build_value_for_dataclass(data_class: Type[T], data: Data, config: Config) -> T:
    if is_instance(data, data_class):
        return data
    return from_dict(
        data_class=data_class,
        data=data,
        config=config,
    )


def _build_value_for_collection(collection: Type, data: Any, config: Config) -> Any:
    collection_cls = extract_origin_collection(collection)
    if is_instance(data, Mapping):
        return collection_cls((key, _build_value(
            type=extract_generic(collection)[1],
            data=value,
            config=Config(forward_references=config.forward_references),  # TODO: is it OK?
        )) for key, value in data.items())
    else:
        return collection_cls(_build_value(
            type=extract_generic(collection)[0],
            data=item,
            config=Config(forward_references=config.forward_references),  # TODO: is it OK?
        ) for item in data)