<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class RiskEvent extends Model
{
    protected $connection = 'exchange';
    protected $table = 'risk_events';
    public $timestamps = false;

    protected $guarded = ['*'];
}
