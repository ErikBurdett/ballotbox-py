from django.shortcuts import render


def home(request):
    return render(request, "core/home.html")


def privacy(request):
    return render(request, "core/privacy.html")


def terms(request):
    return render(request, "core/terms.html")


def resources(request):
    return render(request, "core/resources.html")

