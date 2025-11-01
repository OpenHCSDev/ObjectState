UI Integration
==============

Examples of integrating lazy-config with user interfaces.

Placeholder Service
-------------------

The ``LazyDefaultPlaceholderService`` helps generate placeholder text for UI forms:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import (
       LazyDataclassFactory,
       LazyDefaultPlaceholderService,
       config_context,
       extract_all_configs,
       get_current_temp_global,
   )

   @dataclass
   class GlobalConfig:
       api_endpoint: str = "https://api.example.com"
       timeout: int = 30

   @dataclass
   class ServiceConfig:
       service_name: str = "my-service"
       api_endpoint: str = None  # Will inherit
       timeout: int = 60  # Override

   # Create lazy versions
   factory = LazyDataclassFactory()
   LazyService = factory.make_lazy_simple(ServiceConfig)

   # Create placeholder service
   placeholder_service = LazyDefaultPlaceholderService()

   # Setup configs
   global_cfg = GlobalConfig(api_endpoint="https://prod.api.com")
   service_cfg = ServiceConfig(service_name="payment")

   with config_context(global_cfg):
       with config_context(service_cfg):
           lazy = LazyService()
           current = get_current_temp_global()
           available_configs = extract_all_configs(current)

           # Generate placeholder text
           if hasattr(placeholder_service, 'get_placeholder_text'):
               placeholder = placeholder_service.get_placeholder_text(
                   lazy,
                   "api_endpoint",
                   available_configs
               )
               print(f"Placeholder: {placeholder}")
               # Example output: "Inherited: https://prod.api.com (from GlobalConfig)"

Form Field Generation
---------------------

Generate form fields with inherited value hints:

.. code-block:: python

   from dataclasses import dataclass, fields
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class FormConfig:
       username: str = "admin"
       email: str = "admin@example.com"
       role: str = "user"
       active: bool = True

   LazyForm = LazyDataclassFactory().make_lazy_simple(FormConfig)

   def generate_form_fields(config_instance):
       """Generate form fields from config."""
       form_fields = []

       for field in fields(config_instance):
           field_info = {
               'name': field.name,
               'type': field.type.__name__,
               'default': getattr(config_instance, field.name),
               'required': field.default is None
           }
           form_fields.append(field_info)

       return form_fields

   # Create config with some values set
   context_cfg = FormConfig(
       username="john_doe",
       email="john@example.com"
   )

   with config_context(context_cfg):
       lazy = LazyForm()
       fields_data = generate_form_fields(lazy)

       for field in fields_data:
           print(f"Field: {field['name']}")
           print(f"  Type: {field['type']}")
           print(f"  Default: {field['default']}")
           print(f"  Required: {field['required']}")
           print()

Configuration Editor
--------------------

Build a configuration editor that shows inheritance:

.. code-block:: python

   from dataclasses import dataclass, fields
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class AppSettings:
       app_name: str = "MyApp"
       theme: str = "light"
       language: str = "en"
       notifications: bool = True

   @dataclass
   class UserSettings(AppSettings):
       username: str = "user"
       theme: str = None  # Inherit from AppSettings
       notifications: bool = False  # Override

   LazyUser = LazyDataclassFactory().make_lazy_simple(UserSettings)

   class ConfigEditor:
       """Simple configuration editor."""

       def __init__(self, lazy_config):
           self.config = lazy_config

       def display_settings(self):
           """Display all settings with their sources."""
           print("Configuration Settings:")
           print("-" * 50)

           for field in fields(self.config):
               value = getattr(self.config, field.name)
               print(f"{field.name}: {value}")

       def update_setting(self, field_name, value):
           """Update a configuration setting."""
           # In real implementation, this would create a new instance
           print(f"Updating {field_name} to {value}")

   # Use the editor
   app_settings = AppSettings(
       app_name="ProductionApp",
       theme="dark"
   )

   user_settings = UserSettings(
       username="alice",
       language="fr"
   )

   with config_context(app_settings):
       with config_context(user_settings):
           lazy_user = LazyUser()
           editor = ConfigEditor(lazy_user)

           editor.display_settings()
           # Shows:
           # app_name: ProductionApp (from AppSettings)
           # theme: dark (inherited from AppSettings)
           # language: fr (from UserSettings)
           # notifications: False (from UserSettings)
           # username: alice (from UserSettings)

Validation with UI Feedback
----------------------------

Validate configuration and provide UI feedback:

.. code-block:: python

   from dataclasses import dataclass
   from typing import List, Tuple
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class ServerConfig:
       host: str = "localhost"
       port: int = 8000
       workers: int = 4
       max_connections: int = 100

   LazyServer = LazyDataclassFactory().make_lazy_simple(ServerConfig)

   def validate_config(config) -> List[Tuple[str, bool, str]]:
       """Validate configuration and return results."""
       results = []

       # Validate port
       if 1 <= config.port <= 65535:
           results.append(("port", True, "Valid port number"))
       else:
           results.append(("port", False, "Port must be between 1 and 65535"))

       # Validate workers
       if config.workers > 0:
           results.append(("workers", True, "Valid worker count"))
       else:
           results.append(("workers", False, "Workers must be positive"))

       # Validate max_connections
       if config.max_connections >= config.workers:
           results.append(("max_connections", True, "Valid max connections"))
       else:
           results.append(("max_connections", False,
                          "Max connections must be >= workers"))

       return results

   # Use validation
   server_cfg = ServerConfig(
       host="production.server.com",
       port=443,
       workers=8,
       max_connections=500
   )

   with config_context(server_cfg):
       lazy = LazyServer()
       validation_results = validate_config(lazy)

       print("Validation Results:")
       print("-" * 50)
       for field, valid, message in validation_results:
           status = "✓" if valid else "✗"
           print(f"{status} {field}: {message}")
