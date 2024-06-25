from turms.config import GeneratorConfig
from graphql.utilities.build_client_schema import GraphQLSchema
from graphql.language.ast import (
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
)
from turms.registry import ClassRegistry
from turms.utils import (
    generate_config_class,
    generate_typename_field,
    get_additional_bases_for_type,
    get_interface_bases,
    target_from_node,
)
import ast
from graphql.type.definition import (
    GraphQLEnumType,
    GraphQLField,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLType,
    GraphQLUnionType,
)

from turms.config import GraphQLTypes


def recurse_annotation(
    node: FieldNode,
    parent: str,
    type: GraphQLType,
    client_schema: GraphQLSchema,
    config: GeneratorConfig,
    subtree: ast.AST,
    registry: ClassRegistry,
    is_optional=True,
) -> ast.AST:
    """Recurse Annotations

    Resolves the type of a field and returns the appropriate annotation.
    If we deal with nested object types it recurses further and generated the objects
    together with the type_field_node method:

    class X(BaseModel):
        a: int

    in this case "a" is generated by type_field_node and "X" is generated by recurse_annotation


    Args:
        node (FieldNode): The node
        type (GraphQLType): The type of the field as specified in the schema
        client_schema (GraphQLSchema): The schema itself
        config (GeneratorConfig): The generator config (with the defaults)
        subtree (ast.AST): The passed subtree
        registry (ClassRegistry): A class registry where classes and their imports are registered
        parent_name (str, optional): If resolving nested types the name of parent. Defaults to "".
        is_optional (bool, optional): A recurse modifier for optional types. Defaults to True.

    Raises:
        NotImplementedError: Not implemneted errors
        NotImplementedError: _description_

    Returns:
        ast.AST: The returned tree
    """

    if isinstance(type, GraphQLUnionType):

        union_class_names = []

        for sub_node in node.selection_set.selections:

            if isinstance(sub_node, FragmentSpreadNode):

                fragment_name = registry.inherit_fragment(sub_node.name.value)
                union_class_names.append(fragment_name)

            if isinstance(sub_node, InlineFragmentNode):
                inline_fragment_name = (
                    f"{parent}{sub_node.type_condition.name.value}InlineFragment"
                )
                inline_fragment_fields = []

                inline_fragment_fields += [
                    generate_typename_field(
                        sub_node.type_condition.name.value, registry, config
                    )
                ]

                for sub_sub_node in sub_node.selection_set.selections:

                    if isinstance(sub_sub_node, FieldNode):
                        sub_sub_node_type = client_schema.get_type(
                            sub_node.type_condition.name.value
                        )

                        if sub_sub_node.name.value == "__typename":
                            continue

                        field_type = sub_sub_node_type.fields[sub_sub_node.name.value]
                        inline_fragment_fields += type_field_node(
                            sub_sub_node,
                            inline_fragment_name,
                            field_type,
                            client_schema,
                            config,
                            subtree,
                            registry,
                        )

                additional_bases = get_additional_bases_for_type(
                    sub_node.type_condition.name.value, config, registry
                )
                cls = ast.ClassDef(
                    inline_fragment_name,
                    bases=additional_bases + [
                ast.Name(id=base.split(".")[-1], ctx=ast.Load())
                for base in config.object_bases
            ],
                    decorator_list=[],
                    keywords=[],
                    body=inline_fragment_fields
                    + generate_config_class(GraphQLTypes.FRAGMENT, config),
                )

                subtree.append(cls)
                union_class_names.append(inline_fragment_name)

        assert (
            len(union_class_names) != 0
        ), f"You have set 'always_resolve_interfaces' to True but you have no sub-fragments in your query of {base_name}"

        if len(union_class_names) > 1:
            registry.register_import("typing.Union")
            union_slice = ast.Tuple(
                elts=[
                    ast.Name(id=clsname, ctx=ast.Load())
                    for clsname in union_class_names
                ],
                ctx=ast.Load(),
            )

            if is_optional:
                registry.register_import("typing.Optional")

                return ast.Subscript(
                    value=ast.Name("Optional", ctx=ast.Load()),
                    slice=ast.Subscript(
                        value=ast.Name("Union", ctx=ast.Load()),
                        slice=union_slice,
                    ),
                    ctx=ast.Load(),
                )
            else:
                registry.register_import("typing.Union")
                return ast.Subscript(
                    value=ast.Name("Union", ctx=ast.Load()),
                    slice=union_slice,
                    ctx=ast.Load(),
                )
        else:
            return ast.Name(id=union_class_names[0], ctx=ast.Load())




    if isinstance(type, GraphQLInterfaceType):
        # Lets Create Base Class to Inherit from for this
        mother_class_fields = []
        target = target_from_node(node)

        # SINGLE SPREAD, AUTO COLLAPSING
        if len(node.selection_set.selections) == 1:
            # If there is only one field and its a fragment, we can just use the fragment

            subnode = node.selection_set.selections[0]
            if isinstance(subnode, FragmentSpreadNode):
                if is_optional:
                    registry.register_import("typing.Optional")
                    return ast.Subscript(
                        value=ast.Name("Optional", ctx=ast.Load()),
                        slice=registry.reference_fragment(subnode.name.value, parent),
                        ctx=ast.Load(),
                    )

                else:
                    return registry.reference_fragment(subnode.name.value, parent)

        base_name = f"{parent}{target.capitalize()}"

        if type.description:
            mother_class_fields.append(
                ast.Expr(value=ast.Constant(value=type.description))
            )

        for sub_node in node.selection_set.selections:

            if isinstance(sub_node, FieldNode):
                if sub_node.name.value == "__typename":
                    continue

                field_type = type.fields[sub_node.name.value]
                mother_class_fields += type_field_node(
                    sub_node,
                    base_name,
                    field_type,
                    client_schema,
                    config,
                    subtree,
                    registry,
                )

        # We first genrate the mother class that will provide common fields of this fragment. This will never be reference
        # though
        mother_class_name = f"{base_name}Base"
        additional_bases = get_additional_bases_for_type(type.name, config, registry)
        body = mother_class_fields if mother_class_fields else [ast.Pass()]

        mother_class = ast.ClassDef(
            mother_class_name,
            bases=get_interface_bases(config, registry) + additional_bases,
            decorator_list=[],
            keywords=[],
            body=body + generate_config_class(GraphQLTypes.FRAGMENT, config),
        )
        subtree.append(mother_class)

        union_class_names = []

        for sub_node in node.selection_set.selections:

            if isinstance(sub_node, FragmentSpreadNode):

                spreaded_fragment_classname = f"{base_name}{sub_node.name.value}"

                cls = ast.ClassDef(
                    spreaded_fragment_classname,
                    bases=[
                        ast.Name(id=mother_class_name, ctx=ast.Load()),
                        ast.Name(
                            id=registry.inherit_fragment(sub_node.name.value),
                            ctx=ast.Load(),
                        ),
                    ],
                    decorator_list=[],
                    keywords=[],
                    body=[ast.Pass()]
                    + generate_config_class(GraphQLTypes.FRAGMENT, config),
                )

                subtree.append(cls)
                union_class_names.append(spreaded_fragment_classname)

            if isinstance(sub_node, InlineFragmentNode):
                inline_fragment_name = (
                    f"{base_name}{sub_node.type_condition.name.value}InlineFragment"
                )
                inline_fragment_fields = []

                inline_fragment_fields += [
                    generate_typename_field(
                        sub_node.type_condition.name.value, registry, config
                    )
                ]

                additional_bases = get_additional_bases_for_type(
                    sub_node.type_condition.name.value, config, registry
                )

                for sub_sub_node in sub_node.selection_set.selections:

                    if isinstance(sub_sub_node, FieldNode):
                        sub_sub_node_type = client_schema.get_type(
                            sub_node.type_condition.name.value
                        )

                        if sub_sub_node.name.value == "__typename":
                            continue

                        field_type = sub_sub_node_type.fields[sub_sub_node.name.value]
                        inline_fragment_fields += type_field_node(
                            sub_sub_node,
                            inline_fragment_name,
                            field_type,
                            client_schema,
                            config,
                            subtree,
                            registry,
                        )

                    elif isinstance(sub_sub_node, FragmentSpreadNode):
                        additional_bases.append(registry.reference_fragment(
                            sub_sub_node.name.value, parent
                        ))

                cls = ast.ClassDef(
                    inline_fragment_name,
                    bases=additional_bases
                    + [
                        ast.Name(id=mother_class_name, ctx=ast.Load()),
                    ],
                    decorator_list=[],
                    keywords=[],
                    body=inline_fragment_fields
                    + generate_config_class(GraphQLTypes.FRAGMENT, config),
                )

                subtree.append(cls)
                union_class_names.append(inline_fragment_name)

        if not config.always_resolve_interfaces:
            union_class_names.append(mother_class_name)

        assert (
            len(union_class_names) != 0
        ), f"You have set 'always_resolve_interfaces' to True but you have no sub-fragments in your query of {base_name}"

        if len(union_class_names) > 1:
            registry.register_import("typing.Union")
            union_slice = ast.Tuple(
                elts=[
                    ast.Name(id=clsname, ctx=ast.Load())
                    for clsname in union_class_names
                ],
                ctx=ast.Load(),
            )

            if is_optional:
                registry.register_import("typing.Optional")

                return ast.Subscript(
                    value=ast.Name("Optional", ctx=ast.Load()),
                    slice=ast.Subscript(
                        value=ast.Name("Union", ctx=ast.Load()),
                        slice=union_slice,
                    ),
                    ctx=ast.Load(),
                )
            else:
                registry.register_import("typing.Union")
                return ast.Subscript(
                    value=ast.Name("Union", ctx=ast.Load()),
                    slice=union_slice,
                    ctx=ast.Load(),
                )
        else:
            if is_optional:
                registry.register_import("typing.Optional")

                return ast.Subscript(
                    value=ast.Name("Optional", ctx=ast.Load()),
                    slice=ast.Name(id=union_class_names[0], ctx=ast.Load()),
                    ctx=ast.Load(),
                )
            return ast.Name(id=union_class_names[0], ctx=ast.Load())

    if isinstance(type, GraphQLObjectType):
        pick_fields = []
        additional_bases = get_additional_bases_for_type(type.name, config, registry)

        target = target_from_node(node)
        object_class_name = f"{parent}{target.capitalize()}"

        if type.description:
            pick_fields.append(ast.Expr(value=ast.Constant(value=type.description)))

        pick_fields += [generate_typename_field(type.name, registry, config)]

        # Single Item collapse
        if len(node.selection_set.selections) == 1:
            sub_node = node.selection_set.selections[0]
            if isinstance(sub_node, FragmentSpreadNode):
                if is_optional:
                    registry.register_import("typing.Optional")
                    return ast.Subscript(
                        value=ast.Name("Optional", ctx=ast.Load()),
                        slice=registry.reference_fragment(
                            sub_node.name.value, parent
                        ),  # needs to be parent not object as reference will be to parent
                        ctx=ast.Load(),
                    )

                else:
                    return registry.reference_fragment(
                        sub_node.name.value, parent
                    )  # needs to be parent not object as reference will be to parent

        for sub_node in node.selection_set.selections:

            if isinstance(sub_node, FragmentSpreadNode):
                additional_bases.append(
                    ast.Name(
                        id=registry.inherit_fragment(sub_node.name.value),
                        ctx=ast.Load(),
                    )
                )

            if isinstance(sub_node, FieldNode):
                if sub_node.name.value == "__typename":
                    continue
                field_type = type.fields[sub_node.name.value]
                pick_fields += type_field_node(
                    sub_node,
                    object_class_name,
                    field_type,
                    client_schema,
                    config,
                    subtree,
                    registry,
                )

            if isinstance(sub_node, InlineFragmentNode):
                raise NotImplementedError("Inline Fragments are not yet implemented")

        body = pick_fields if pick_fields else [ast.Pass()]

        cls = ast.ClassDef(
            object_class_name,
            bases=additional_bases
            + [
                ast.Name(id=base.split(".")[-1], ctx=ast.Load())
                for base in config.object_bases
            ],
            decorator_list=[],
            keywords=[],
            body=body + generate_config_class(GraphQLTypes.OBJECT, config),
        )

        subtree.append(cls)

        if is_optional:
            registry.register_import("typing.Optional")
            return ast.Subscript(
                value=ast.Name("Optional", ctx=ast.Load()),
                slice=ast.Name(
                    id=object_class_name,
                    ctx=ast.Load(),
                ),
                ctx=ast.Load(),
            )

        else:
            return ast.Name(
                id=object_class_name,
                ctx=ast.Load(),
            )

    if isinstance(type, GraphQLScalarType):

        if is_optional:
            registry.register_import("typing.Optional")
            return ast.Subscript(
                value=ast.Name("Optional", ctx=ast.Load()),
                slice=registry.reference_scalar(type.name),
            )

        else:
            return registry.reference_scalar(type.name)

    if isinstance(type, GraphQLEnumType):

        if is_optional:
            registry.register_import("typing.Optional")
            return ast.Subscript(
                value=ast.Name("Optional", ctx=ast.Load()),
                slice=registry.reference_enum(type.name, parent),
            )

        else:
            return registry.reference_enum(type.name, parent)

    if isinstance(type, GraphQLNonNull):
        return recurse_annotation(
            node,
            parent,
            type.of_type,
            client_schema,
            config,
            subtree,
            registry,
            is_optional=False,
        )

    if isinstance(type, GraphQLList):

        if config.freeze.enabled:
            registry.register_import("typing.Tuple")
            def list_builder(x):
                return ast.Subscript(value=ast.Name("Tuple", ctx=ast.Load()), slice=ast.Tuple(elts=[x, ast.Ellipsis()], ctx=ast.Load()), ctx=ast.Load())

        else:

            registry.register_import("typing.List")
            def list_builder(x):
                return ast.Subscript(value=ast.Name("List", ctx=ast.Load()), slice=x, ctx=ast.Load())

        if is_optional:
            registry.register_import("typing.Optional")

            return ast.Subscript(
                value=ast.Name("Optional", ctx=ast.Load()),
                slice=list_builder(
                    recurse_annotation(
                        node,
                        parent,
                        type.of_type,
                        client_schema,
                        config,
                        subtree,
                        registry,
                    )
                ),
                ctx=ast.Load(),
            )

        else:
            return list_builder(
                recurse_annotation(
                    node,
                    parent,
                    type.of_type,
                    client_schema,
                    config,
                    subtree,
                    registry,
                )
            )


def type_field_node(
    node: FieldNode,
    parent: str,
    field: GraphQLField,
    client_schema: GraphQLSchema,
    config: GeneratorConfig,
    subtree: ast.AST,
    registry: ClassRegistry,
    is_optional=True,
):
    """Types a field node

    This

    Args:
        node (FieldNode): _description_
        field (GraphQLField): _description_
        client_schema (GraphQLSchema): _description_
        config (GeneratorConfig): _description_
        subtree (ast.AST): _description_
        registry (ClassRegistry): _description_
        parent_name (str, optional): _description_. Defaults to "".
        is_optional (bool, optional): _description_. Defaults to True.

    Returns:
        _type_: _description_
    """

    target = target_from_node(node)
    field_name = registry.generate_node_name(target)

    if target != field_name:
        registry.register_import("pydantic.Field")
        assign = ast.AnnAssign(
            target=ast.Name(field_name, ctx=ast.Store()),
            annotation=recurse_annotation(
                node,
                parent,
                field.type,
                client_schema,
                config,
                subtree,
                registry,
                is_optional=is_optional,
            ),
            value=ast.Call(
                func=ast.Name(id="Field", ctx=ast.Load()),
                args=[],
                keywords=[ast.keyword(arg="alias", value=ast.Constant(value=target))],
            ),
            simple=1,
        )
    else:
        assign = ast.AnnAssign(
            target=ast.Name(target, ctx=ast.Store()),
            annotation=recurse_annotation(
                node,
                parent,
                field.type,
                client_schema,
                config,
                subtree,
                registry,
                is_optional=is_optional,
            ),
            simple=1,
        )

    potential_comment = (
        field.description
        if not field.deprecation_reason
        else f"DEPRECATED {field.deprecation_reason}: : {field.description} "
    )

    if field.deprecation_reason:
        registry.warn(
            f"Field {node.name.value} on {parent} is deprecated: {field.deprecation_reason}"
        )

    if potential_comment:
        return [assign, ast.Expr(value=ast.Constant(value=potential_comment))]

    return [assign]
