class DualAccessDict(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"No attribute '{name}'")

    def __setattr__(self, name, value):
        if name == "_store":
            super().__setattr__(name, value)
        else:
            self[name] = value

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)

    # def __repr__(self):
    #     return f"{self.__class__.__name__}({self.items()})"

if __name__ == "__main__":
    dad = DualAccessDict(a=1, b=2)
    print(dad.a)      # Access as attribute
    print(dad['b'])   # Access as dictionary item
    dad.c = 3         # Set as attribute
    dad['d'] = 4      # Set as dictionary item
    print(dad)        # Show all items