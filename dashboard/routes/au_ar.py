"""Antibiotic Usage (AU) and Antimicrobial Resistance (AR) reporting routes."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app, Response

# Add nhsn-reporting to path
nhsn_path = Path(__file__).parent.parent.parent / "nhsn-reporting"
if str(nhsn_path) not in sys.path:
    sys.path.insert(0, str(nhsn_path))

au_ar_bp = Blueprint("au_ar", __name__, url_prefix="/au-ar")


def get_au_extractor():
    """Get or create AU data extractor instance."""
    if not hasattr(current_app, "au_extractor"):
        from src.data import AUDataExtractor
        current_app.au_extractor = AUDataExtractor()
    return current_app.au_extractor


def get_ar_extractor():
    """Get or create AR data extractor instance."""
    if not hasattr(current_app, "ar_extractor"):
        from src.data import ARDataExtractor
        current_app.ar_extractor = ARDataExtractor()
    return current_app.ar_extractor


def get_denominator_calculator():
    """Get or create denominator calculator instance."""
    if not hasattr(current_app, "denominator_calc"):
        from src.data import DenominatorCalculator
        current_app.denominator_calc = DenominatorCalculator()
    return current_app.denominator_calc


@au_ar_bp.route("/")
def dashboard():
    """AU/AR reporting dashboard overview."""
    try:
        au_extractor = get_au_extractor()
        ar_extractor = get_ar_extractor()
        denom_calc = get_denominator_calculator()

        # Get current month and quarter
        today = date.today()
        current_month = today.strftime("%Y-%m")
        current_quarter = (today.month - 1) // 3 + 1
        current_year = today.year

        # Get date range for current month
        month_start = today.replace(day=1)
        month_end = today

        # Get AU summary for current month (may be empty if no data)
        try:
            au_summary = au_extractor.get_monthly_summary(
                start_date=month_start,
                end_date=month_end,
            )
        except Exception as e:
            current_app.logger.warning(f"AU summary failed: {e}")
            au_summary = {
                "date_range": {"start": str(month_start), "end": str(month_end)},
                "locations": [],
                "overall_totals": {"total_dot": 0, "total_patient_days": 0, "dot_per_1000_pd": 0},
            }

        # Get AR summary for current quarter (may be empty if no data)
        try:
            ar_summary = ar_extractor.get_quarterly_summary(
                year=current_year,
                quarter=current_quarter,
            )
        except Exception as e:
            current_app.logger.warning(f"AR summary failed: {e}")
            ar_summary = {
                "period": {
                    "year": current_year,
                    "quarter": current_quarter,
                    "quarter_string": f"{current_year}-Q{current_quarter}",
                },
                "overall_totals": {"total_cultures": 0, "first_isolates": 0, "unique_organisms": 0},
                "locations": [],
                "phenotypes": [],
            }

        # Get denominator summary (may be empty if no data)
        try:
            denom_summary = denom_calc.get_denominator_summary(
                start_date=month_start,
                end_date=month_end,
            )
        except Exception as e:
            current_app.logger.warning(f"Denominator summary failed: {e}")
            denom_summary = {
                "date_range": {"start": str(month_start), "end": str(month_end)},
                "locations": [],
            }

        return render_template(
            "au_ar_dashboard.html",
            au_summary=au_summary,
            ar_summary=ar_summary,
            denom_summary=denom_summary,
            current_month=current_month,
            current_year=current_year,
            current_quarter=current_quarter,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AU/AR dashboard: {e}")
        return render_template(
            "au_ar_dashboard.html",
            au_summary=None,
            ar_summary=None,
            denom_summary=None,
            current_month=date.today().strftime("%Y-%m"),
            current_year=date.today().year,
            current_quarter=(date.today().month - 1) // 3 + 1,
            error=str(e),
        )


@au_ar_bp.route("/au")
def au_detail():
    """Detailed Antibiotic Usage reporting page."""
    try:
        au_extractor = get_au_extractor()

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        # Default to last 3 months
        today = date.today()
        if not from_date_str:
            from_date = today.replace(day=1) - timedelta(days=60)
            from_date = from_date.replace(day=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

        if not to_date_str:
            to_date = today
        else:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

        locations = [location] if location else None

        # Get AU data
        au_summary = au_extractor.get_monthly_summary(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )

        # Get category breakdown
        category_df = au_extractor.get_usage_by_category(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )
        category_data = category_df.to_dict("records") if not category_df.empty else []

        # Get available locations for filter
        all_locations = set()
        for loc in au_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "au_detail.html",
            au_summary=au_summary,
            category_data=category_data,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            current_location=location or "",
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AU detail: {e}")
        today = date.today()
        return render_template(
            "au_detail.html",
            au_summary=None,
            category_data=[],
            from_date=(today - timedelta(days=90)).strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            current_location="",
            available_locations=[],
            error=str(e),
        )


@au_ar_bp.route("/ar")
def ar_detail():
    """Detailed Antimicrobial Resistance reporting page."""
    try:
        ar_extractor = get_ar_extractor()

        # Get parameters
        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        # Default to current quarter
        today = date.today()
        if not year:
            year = today.year
        if not quarter:
            quarter = (today.month - 1) // 3 + 1

        locations = [location] if location else None

        # Get AR data
        ar_summary = ar_extractor.get_quarterly_summary(
            locations=locations,
            year=year,
            quarter=quarter,
        )

        # Get resistance rates
        resistance_df = ar_extractor.calculate_resistance_rates(
            locations=locations,
            year=year,
            quarter=quarter,
        )
        resistance_data = resistance_df.to_dict("records") if not resistance_df.empty else []

        # Get phenotype data
        phenotype_df = ar_extractor.calculate_phenotypes(
            locations=locations,
            year=year,
            quarter=quarter,
        )
        phenotype_data = phenotype_df.to_dict("records") if not phenotype_df.empty else []

        # Available quarters for filter
        quarters = []
        for y in range(year - 1, year + 1):
            for q in range(1, 5):
                if y < year or (y == year and q <= (today.month - 1) // 3 + 1):
                    quarters.append({"year": y, "quarter": q, "label": f"{y}-Q{q}"})

        # Available locations
        all_locations = set()
        for loc in ar_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "ar_detail.html",
            ar_summary=ar_summary,
            resistance_data=resistance_data,
            phenotype_data=phenotype_data,
            year=year,
            quarter=quarter,
            current_location=location or "",
            available_quarters=quarters,
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading AR detail: {e}")
        today = date.today()
        return render_template(
            "ar_detail.html",
            ar_summary=None,
            resistance_data=[],
            phenotype_data=[],
            year=today.year,
            quarter=(today.month - 1) // 3 + 1,
            current_location="",
            available_quarters=[],
            available_locations=[],
            error=str(e),
        )


@au_ar_bp.route("/denominators")
def denominators():
    """Denominator data reporting page (device-days, patient-days)."""
    try:
        denom_calc = get_denominator_calculator()

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        # Default to last 3 months
        today = date.today()
        if not from_date_str:
            from_date = today.replace(day=1) - timedelta(days=60)
            from_date = from_date.replace(day=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

        if not to_date_str:
            to_date = today
        else:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

        locations = [location] if location else None

        # Get denominator summary
        denom_summary = denom_calc.get_denominator_summary(
            locations=locations,
            start_date=from_date,
            end_date=to_date,
        )

        # Get individual data series for detailed view
        patient_days_df = denom_calc.get_patient_days(locations, from_date, to_date)
        line_days_df = denom_calc.get_central_line_days(locations, from_date, to_date)
        catheter_days_df = denom_calc.get_urinary_catheter_days(locations, from_date, to_date)
        vent_days_df = denom_calc.get_ventilator_days(locations, from_date, to_date)

        # Convert to records for template
        patient_days_data = patient_days_df.to_dict("records") if not patient_days_df.empty else []
        line_days_data = line_days_df.to_dict("records") if not line_days_df.empty else []
        catheter_days_data = catheter_days_df.to_dict("records") if not catheter_days_df.empty else []
        vent_days_data = vent_days_df.to_dict("records") if not vent_days_df.empty else []

        # Available locations
        all_locations = set()
        for loc in denom_summary.get("locations", []):
            all_locations.add(loc["nhsn_location_code"])

        return render_template(
            "denominators.html",
            denom_summary=denom_summary,
            patient_days_data=patient_days_data,
            line_days_data=line_days_data,
            catheter_days_data=catheter_days_data,
            vent_days_data=vent_days_data,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            current_location=location or "",
            available_locations=sorted(all_locations),
        )
    except Exception as e:
        current_app.logger.error(f"Error loading denominators: {e}")
        today = date.today()
        return render_template(
            "denominators.html",
            denom_summary=None,
            patient_days_data=[],
            line_days_data=[],
            catheter_days_data=[],
            vent_days_data=[],
            from_date=(today - timedelta(days=90)).strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            current_location="",
            available_locations=[],
            error=str(e),
        )


# API Endpoints

@au_ar_bp.route("/api/au/summary")
def api_au_summary():
    """Get AU summary as JSON."""
    try:
        au_extractor = get_au_extractor()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        summary = au_extractor.get_monthly_summary(locations, from_date, to_date)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@au_ar_bp.route("/api/ar/summary")
def api_ar_summary():
    """Get AR summary as JSON."""
    try:
        ar_extractor = get_ar_extractor()

        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        locations = [location] if location else None

        summary = ar_extractor.get_quarterly_summary(locations, year, quarter)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@au_ar_bp.route("/api/denominators")
def api_denominators():
    """Get denominator data as JSON."""
    try:
        denom_calc = get_denominator_calculator()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        summary = denom_calc.get_denominator_summary(locations, from_date, to_date)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@au_ar_bp.route("/api/au/export")
def api_au_export():
    """Export AU data as CSV for NHSN submission."""
    try:
        import csv
        import io

        au_extractor = get_au_extractor()

        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        location = request.args.get("location")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else None
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else None
        locations = [location] if location else None

        nhsn_df = au_extractor.export_for_nhsn(locations, from_date, to_date)

        if nhsn_df.empty:
            return jsonify({"error": "No data to export"}), 404

        output = io.StringIO()
        nhsn_df.to_csv(output, index=False)
        output.seek(0)

        filename = f"nhsn_au_export_{from_date_str or 'all'}_to_{to_date_str or 'now'}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@au_ar_bp.route("/api/ar/export")
def api_ar_export():
    """Export AR data as CSV for NHSN submission."""
    try:
        import csv
        import io

        ar_extractor = get_ar_extractor()

        year = request.args.get("year", type=int)
        quarter = request.args.get("quarter", type=int)
        location = request.args.get("location")

        locations = [location] if location else None

        export_data = ar_extractor.export_for_nhsn(locations, year, quarter)

        if export_data["isolates"].empty:
            return jsonify({"error": "No data to export"}), 404

        # Create a zip-like response with both CSVs
        output = io.StringIO()
        output.write("# NHSN AR Export - Isolates\n")
        export_data["isolates"].to_csv(output, index=False)
        output.write("\n\n# NHSN AR Export - Susceptibilities\n")
        export_data["susceptibilities"].to_csv(output, index=False)
        output.seek(0)

        filename = f"nhsn_ar_export_{year or 'all'}_Q{quarter or 'all'}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@au_ar_bp.route("/help")
def help_page():
    """AU/AR Help and Demo Guide."""
    return render_template("au_ar_help.html")


@au_ar_bp.route("/submission")
def submission():
    """AU/AR NHSN submission page."""
    try:
        au_extractor = get_au_extractor()
        ar_extractor = get_ar_extractor()

        # Get parameters
        submission_type = request.args.get("type", "au")  # 'au' or 'ar'

        today = date.today()

        if submission_type == "au":
            # AU is monthly
            from_date_str = request.args.get("from_date")
            to_date_str = request.args.get("to_date")

            if not from_date_str:
                # Default to previous month
                prev_month = today.replace(day=1) - timedelta(days=1)
                from_date = prev_month.replace(day=1)
            else:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()

            if not to_date_str:
                to_date = today.replace(day=1) - timedelta(days=1)
            else:
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

            au_summary = au_extractor.get_monthly_summary(start_date=from_date, end_date=to_date)

            return render_template(
                "au_ar_submission.html",
                submission_type="au",
                au_summary=au_summary,
                ar_summary=None,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                year=None,
                quarter=None,
            )

        else:
            # AR is quarterly
            year = request.args.get("year", type=int) or today.year
            quarter = request.args.get("quarter", type=int)

            if not quarter:
                # Default to previous quarter
                current_quarter = (today.month - 1) // 3 + 1
                if current_quarter == 1:
                    year -= 1
                    quarter = 4
                else:
                    quarter = current_quarter - 1

            ar_summary = ar_extractor.get_quarterly_summary(year=year, quarter=quarter)

            return render_template(
                "au_ar_submission.html",
                submission_type="ar",
                au_summary=None,
                ar_summary=ar_summary,
                from_date=None,
                to_date=None,
                year=year,
                quarter=quarter,
            )

    except Exception as e:
        current_app.logger.error(f"Error loading AU/AR submission: {e}")
        today = date.today()
        return render_template(
            "au_ar_submission.html",
            submission_type=request.args.get("type", "au"),
            au_summary=None,
            ar_summary=None,
            from_date=(today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d"),
            to_date=(today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d"),
            year=today.year,
            quarter=(today.month - 1) // 3 + 1,
            error=str(e),
        )
